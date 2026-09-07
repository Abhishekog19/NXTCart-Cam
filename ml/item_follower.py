# ---------------------------------------------------------------
# ml/item_follower.py  --  FOLLOW ONE ITEM, NOT "THE BIGGEST BLOB"
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The verifier needs clean crops of the ONE product the shopper just
# scanned, taken as it travels from the scanner into the cart.  The naive
# way to get them — "each frame, grab the largest blob" — is WRONG and
# dangerous: between frames the largest blob can flip from the product to
# the hand carrying it, to a second product, to a shadow.  Verify a mix of
# those crops and you are no longer answering "is THIS item the scanned
# SKU"; you are answering nothing.
#
# So this module LOCKS one target and FOLLOWS it:
#
#   1. LOCK   the first qualifying detection whose centroid is inside the
#             SCANNER_REGION becomes the target.  (The scan just happened
#             there, so that is where the scanned item appears.)
#   2. FOLLOW each subsequent frame, associate the target to AT MOST ONE
#             detection by centroid distance + IoU — the same geometry the
#             identity tracker uses, simplified to a single target.
#   3. GUARD  continuity actively:
#               • two detections contest the target      -> AMBIGUOUS
#               • the matched blob is far bigger than the -> MERGED
#                 target's established size (hand+item or
#                 two items fused into one blob)
#               • no acceptable detection for a while     -> LOST
#             ANY of these ends the transaction as RETRY.  We never quietly
#             re-lock onto whatever is biggest — a broken chain of custody
#             must be admitted, not hidden.
#   4. ARRIVE the target's centroid entering CART_ENTRY_REGION is REACHED_CART,
#             the spatial half of "the item actually went in the cart".
#
# Crops are kept only when the view is usable (ml/visibility.py) and are
# SAMPLED ACROSS THE WHOLE TRAJECTORY, not just the last few frames, so the
# verifier sees the item from the range of angles it passed through.  Each
# kept crop is deduped by frame `seq`, so re-reading one physical frame can
# never contribute two crops (and therefore never two votes).
# ---------------------------------------------------------------

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ml.config import (
    ASSOC_AMBIGUOUS_MARGIN,
    ASSOC_MAX_CENTROID_DIST,
    ASSOC_MIN_IOU,
    CART_ENTRY_REGION,
    IMAGE_SIZE,
    MERGE_AREA_RATIO,
    SCANNER_REGION,
    VERIFY_BURST_FRAMES,
    VERIFY_LOST_GRACE_FRAMES,
)
from ml.detector import Detection
from ml.visibility import assess

BBox = Tuple[int, int, int, int]


class FollowStatus:
    """Where the single-target follow stands this frame (strings for logs)."""
    WAITING      = "WAITING"       # locked nothing yet; watching scanner region
    TRACKING     = "TRACKING"      # following the target normally
    REACHED_CART = "REACHED_CART"  # target entered the cart-entry region
    AMBIGUOUS    = "AMBIGUOUS"     # 2+ detections contest the target -> RETRY
    MERGED       = "MERGED"        # blob fused with hand/other item  -> RETRY
    LOST         = "LOST"          # continuity broken                -> RETRY

    # The statuses that mean "chain of custody is broken, do not trust crops".
    BROKEN = {AMBIGUOUS, MERGED, LOST}


@dataclass
class KeptCrop:
    """One clean crop of the target, tagged with the frame that produced it."""
    seq: int
    ts: float
    crop: np.ndarray


def _centroid(bbox: BBox) -> Tuple[float, float]:
    x, y, w, h = bbox
    return (x + w / 2.0, y + h / 2.0)


def _iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / float(union) if union > 0 else 0.0


def _region_px(region: Tuple[float, float, float, float],
               frame_w: int, frame_h: int) -> BBox:
    l, t, r, b = region
    return (int(l * frame_w), int(t * frame_h),
            int((r - l) * frame_w), int((b - t) * frame_h))


def _point_in(px_box: BBox, pt: Tuple[float, float]) -> bool:
    x, y, w, h = px_box
    cx, cy = pt
    return x <= cx <= x + w and y <= cy <= y + h


class ItemFollower:
    """
    Locks and follows ONE item from the scanner region toward the cart.

    Lifecycle: construct per transaction, call update(detections, frame, meta)
    once per frame, read `.status`.  When `.status` is REACHED_CART the crops
    in `.crops` are ready for the verifier; when `.status` is in
    FollowStatus.BROKEN the transaction must resolve RETRY.
    """

    def __init__(self, frame_size: Tuple[int, int]) -> None:
        self.frame_w, self.frame_h = frame_size
        self._scanner_box = _region_px(SCANNER_REGION, self.frame_w, self.frame_h)
        self._cart_box = _region_px(CART_ENTRY_REGION, self.frame_w, self.frame_h)

        self.status: str = FollowStatus.WAITING
        self.target_bbox: Optional[BBox] = None
        self._baseline_area: Optional[float] = None   # target's established size
        self._misses = 0
        self.reached_cart = False

        # Kept crops, keyed by seq so one physical frame contributes once.
        self._kept: List[KeptCrop] = []
        self._seen_seq: set = set()
        # A breadcrumb trail of centroids for the UI.
        self.trail: List[Tuple[int, int]] = []

    # ── public API ────────────────────────────────────────────────

    @property
    def crops(self) -> List[np.ndarray]:
        """The kept crops, sampled evenly across the trajectory."""
        return _sample_even([k.crop for k in self._kept], VERIFY_BURST_FRAMES)

    @property
    def usable_crop_count(self) -> int:
        return len(self._kept)

    def update(self, detections: List[Detection], frame: np.ndarray,
               meta) -> str:
        """
        Advance the follow by one frame.  `meta` is a FrameMeta (seq, ts);
        detections already came from the detector for THIS frame.  Returns
        the new status.
        """
        # A physical frame seen twice must not be processed twice — that is
        # the whole point of the seq stamp.
        if meta is not None and meta.seq in self._seen_seq:
            return self.status
        if meta is not None:
            self._seen_seq.add(meta.seq)

        if self.status in FollowStatus.BROKEN:
            return self.status

        # ── not locked yet: look for the item in the scanner region ──
        if self.target_bbox is None:
            return self._try_lock(detections, frame, meta)

        # ── locked: associate the target to at most one detection ────
        return self._follow(detections, frame, meta)

    # ── lock ──────────────────────────────────────────────────────

    def _try_lock(self, detections: List[Detection], frame: np.ndarray,
                  meta) -> str:
        """Lock the first detection whose centroid is in the scanner region."""
        candidates = [d for d in detections
                      if _point_in(self._scanner_box, d.centroid)]
        if not candidates:
            self.status = FollowStatus.WAITING
            return self.status
        # If several appear at once in the scanner region we cannot know which
        # is the scanned item — wait for the scene to simplify rather than
        # guessing.  (A guess here is exactly the failure mode we forbid.)
        if len(candidates) > 1:
            self.status = FollowStatus.WAITING
            return self.status

        target = candidates[0]
        self.target_bbox = target.bbox
        self._baseline_area = float(max(target.area, 1))
        self._misses = 0
        self.status = FollowStatus.TRACKING
        self._record_crop(target, frame, meta)
        self._record_trail(target)
        return self.status

    # ── follow ─────────────────────────────────────────────────────

    def _follow(self, detections: List[Detection], frame: np.ndarray,
                meta) -> str:
        scored = [(self._assoc_score(d), d) for d in detections]
        scored = [(s, d) for (s, d) in scored if s is not None]
        scored.sort(key=lambda sd: sd[0], reverse=True)

        if not scored:
            # Nothing matched the target this frame.  Tolerate a brief gap
            # (the hand momentarily covering the item), then give up — a real
            # loss of continuity must not be papered over.
            self._misses += 1
            if self._misses > VERIFY_LOST_GRACE_FRAMES:
                self.status = FollowStatus.LOST
            return self.status

        best_score, best = scored[0]

        # Two detections both look like the target -> we cannot tell which
        # one IS the target.  Ambiguity is a broken chain, not a coin flip.
        if len(scored) >= 2 and (best_score - scored[1][0]) < ASSOC_AMBIGUOUS_MARGIN:
            self.status = FollowStatus.AMBIGUOUS
            return self.status

        # The matched blob is far larger than the target's established size:
        # the item has fused with the hand or another item into one blob, so
        # its crop is contaminated and its centroid untrustworthy.
        if self._baseline_area and best.area > MERGE_AREA_RATIO * self._baseline_area:
            self.status = FollowStatus.MERGED
            return self.status

        # Good, unambiguous match — advance the target.
        self._misses = 0
        self.target_bbox = best.bbox
        # Let the baseline grow slowly toward the item's true size but never
        # jump (a jump would be the very merge we just guarded against).
        self._baseline_area = max(self._baseline_area or best.area,
                                  float(best.area))
        self._record_crop(best, frame, meta)
        self._record_trail(best)

        if _point_in(self._cart_box, best.centroid):
            self.reached_cart = True
            self.status = FollowStatus.REACHED_CART
        else:
            self.status = FollowStatus.TRACKING
        return self.status

    def _assoc_score(self, det: Detection) -> Optional[float]:
        """
        How well `det` matches the current target, or None if it is not a
        plausible match at all.  Combines centroid proximity and IoU, exactly
        the cues the identity tracker uses — just for one target.
        """
        assert self.target_bbox is not None
        tc = _centroid(self.target_bbox)
        dc = det.centroid
        dist = math.hypot(tc[0] - dc[0], tc[1] - dc[1])
        iou = _iou(self.target_bbox, det.bbox)
        if dist > ASSOC_MAX_CENTROID_DIST and iou < ASSOC_MIN_IOU:
            return None
        # Normalise distance to [0,1] (closer = higher) and average with IoU.
        prox = 1.0 - min(dist / ASSOC_MAX_CENTROID_DIST, 1.0)
        return 0.5 * prox + 0.5 * iou

    # ── crop keeping ────────────────────────────────────────────────

    def _record_crop(self, det: Detection, frame: np.ndarray, meta) -> None:
        crop = det.crop(frame)
        if not assess(crop).usable:
            return
        # Downscale to the model's input size on capture so the buffer stays
        # small regardless of how big the detection was on screen.
        small = cv2.resize(crop, (IMAGE_SIZE, IMAGE_SIZE))
        seq = meta.seq if meta is not None else len(self._kept)
        ts = meta.ts if meta is not None else 0.0
        self._kept.append(KeptCrop(seq=seq, ts=ts, crop=small))
        # Keep the buffer bounded; if it overflows, thin it evenly rather than
        # dropping the oldest, so we retain coverage of the whole path.
        if len(self._kept) > VERIFY_BURST_FRAMES * 3:
            self._kept = _sample_even_objs(self._kept, VERIFY_BURST_FRAMES * 2)

    def _record_trail(self, det: Detection) -> None:
        cx, cy = det.centroid
        self.trail.append((int(cx), int(cy)))
        if len(self.trail) > 64:
            self.trail = self.trail[-64:]

    # ── UI helpers ──────────────────────────────────────────────────

    @property
    def scanner_box(self) -> BBox:
        return self._scanner_box

    @property
    def cart_box(self) -> BBox:
        return self._cart_box


def _sample_even(items: list, k: int) -> list:
    """Return at most k items spread evenly across the list (keeps ends)."""
    n = len(items)
    if n <= k:
        return list(items)
    idx = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    return [items[i] for i in idx]


def _sample_even_objs(items: list, k: int) -> list:
    return _sample_even(items, k)
