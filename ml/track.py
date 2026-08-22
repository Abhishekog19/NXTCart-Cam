# ---------------------------------------------------------------
# ml/track.py  --  THE TRACK OBJECT + STATE MACHINE
#
# A Track is the memory of ONE physical item.  It is the thing that makes
# identity persistent: a detection is momentary ("a blob is here this
# frame"), but a Track lives across frames and remembers WHO the blob is.
#
# THE ONE RULE THAT MATTERS MOST
# ───────────────────────────────
# Once a track is CONFIRMED, its `product_id` and its `identity_embedding`
# are LOCKED.  They are written exactly once, from a clean high-visibility
# frame, and never changed again — not by a low-confidence match, not by a
# partial-occlusion crop, not by rotation, not by anything.  This is the
# whole fix for the "system changes its mind when items overlap" bug.
#
# STATE MACHINE
# ──────────────
#   NEW ─▶ VERIFYING ─▶ CONFIRMED ─▶ PRESENT
#                                       │
#              (settled, in the cart)   │
#                                       ├─▶ MOVING ─▶ EXITING ─▶ REMOVED
#                                       │      (real motion out of the zone,
#                                       │       across the boundary — the
#                                       │       ONLY path that leaves the cart)
#                                       │
#                                       └─▶ OCCLUDED ─▶ LOST ─▶ REACQUIRE ─▶ PRESENT
#                                              (temporarily hidden / untracked —
#                                               STILL counts as in the cart)
#
# Counting rule (see cart_state.py): a track counts toward the cart the
# moment it has a locked product_id and keeps counting until — and only
# until — it reaches REMOVED.  Low visibility, low confidence or a lost
# track NEVER remove it.
# ---------------------------------------------------------------

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

from ml.config import (
    EVIDENCE_BUFFER_MAX,
    MERGE_AREA_RATIO,
    MOVING_MIN_DISPLACEMENT,
    PRESENCE_TEMPLATE_PX,
)

BBox = Tuple[int, int, int, int]


class TrackState:
    """String constants for every state (kept as strings for easy logging)."""
    NEW       = "NEW"        # just detected, no identity yet
    VERIFYING = "VERIFYING"  # gathering good-frame evidence to identify
    CONFIRMED = "CONFIRMED"  # identity locked this frame
    PRESENT   = "PRESENT"    # settled, sitting in the cart, fully tracked
    MOVING    = "MOVING"     # locked item is moving (maybe toward the exit)
    EXITING   = "EXITING"    # moving across the exit boundary
    REMOVED   = "REMOVED"    # confirmed physical exit — drops out of cart
    OCCLUDED  = "OCCLUDED"   # hidden but still matched to ~its location
    LOST      = "LOST"       # no match for a while — STILL counts in cart
    REACQUIRE = "REACQUIRE"  # a detection re-matched this track's locked id

    # Once a track has a locked identity, these are the states in which it
    # still counts as physically in the cart.  (Everything except REMOVED.)
    COUNTED = {CONFIRMED, PRESENT, MOVING, EXITING, OCCLUDED, LOST, REACQUIRE}
    # A track that reaches this is gone for good.
    TERMINAL = {REMOVED}
    # Not yet identified — never counts, safe to prune if it vanishes.
    UNIDENTIFIED = {NEW, VERIFYING}


def _iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / float(union) if union > 0 else 0.0


class Track:
    """The persistent identity of one item.  See module docstring."""

    def __init__(self, track_id: int, bbox: BBox, frame_idx: int,
                 quality: float = 1.0) -> None:
        self.track_id = track_id
        self.bbox: BBox = bbox

        # ── Identity (locked once CONFIRMED) ──────────────────────
        self.product_id: Optional[str] = None            # None until locked
        self.identity_embedding: Optional[np.ndarray] = None  # written ONCE
        self._locked: bool = False

        # ── Temporary verification evidence (discarded after CONFIRM) ─
        # Each entry: {"emb": vector, "result": match_dict, "vis": float}
        self.recent_embeddings: List[dict] = []

        # ── Live status ───────────────────────────────────────────
        self.recognition_confidence: float = 0.0
        self.visibility_ratio: float = 1.0
        # Visibility on the PREVIOUS observed frame.  A big upward jump means
        # an occluder just moved off this item, which makes the box (and so
        # the centroid) change shape for reasons that have nothing to do with
        # the item moving.  The exit logic uses this to avoid reading a
        # de-occlusion as motion.
        self.prev_visibility_ratio: float = 1.0
        self.state: str = TrackState.NEW
        self.last_seen: int = frame_idx
        self.frames_in_current_state: int = 0
        self.created_frame: int = frame_idx

        # ── Geometry / motion bookkeeping ─────────────────────────
        self._max_area: float = float(bbox[2] * bbox[3])
        self._centroids: Deque[Tuple[float, float]] = deque(maxlen=6)
        self._centroids.append(self._centroid_of(bbox))
        self.exit_progress: int = 0          # consecutive boundary-directed frames
        self.observations: int = 0           # frames where a box was accepted
        # Consecutive observed frames this track has barely moved.  Recognition
        # is expensive and unreliable on a moving, half-gripped item, so the
        # verify gate spends inferences only on tracks that have settled.
        self.still_frames: int = 0

        # ── Inference bookkeeping ─────────────────────────────────
        # How many times we have paid for recognition on this track.  Only
        # used to pick fairly between competing candidates when the per-frame
        # inference budget forces us to choose: fewest attempts goes first, so
        # no track is starved and time-to-lock stays bounded.
        self.recognition_attempts: int = 0

        # ── Static presence evidence (see identity_tracker) ───────
        # A small grayscale patch of what this item looks like where it sits,
        # captured from clean high-visibility frames.  It answers "is the item
        # still there?" on frames where the motion detector reports nothing —
        # a question detection alone cannot answer for a stationary object.
        self.presence_template: Optional[np.ndarray] = None
        # Consecutive frames the item's spot has looked like empty background.
        # Real departure evidence; any non-vacated frame resets it to 0.
        self.vacated_frames: int = 0

        # ── Debug / metrics ───────────────────────────────────────
        # (frame_idx, from_state, to_state, reason)
        self.transitions: List[Tuple[int, str, str, str]] = []

    # ─────────────────────────────────────────────────────────────
    # GEOMETRY
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _centroid_of(bbox: BBox) -> Tuple[float, float]:
        x, y, w, h = bbox
        return (x + w / 2.0, y + h / 2.0)

    @property
    def centroid(self) -> Tuple[float, float]:
        return self._centroids[-1]

    @property
    def area(self) -> float:
        return float(self.bbox[2] * self.bbox[3])

    def iou(self, bbox: BBox) -> float:
        return _iou(self.bbox, bbox)

    def centroid_distance(self, bbox: BBox) -> float:
        cx, cy = self.centroid
        ox, oy = self._centroid_of(bbox)
        return math.hypot(cx - ox, cy - oy)

    def displacement(self) -> float:
        """How far the centroid moved between the last two updates (px)."""
        if len(self._centroids) < 2:
            return 0.0
        (x1, y1), (x2, y2) = self._centroids[-2], self._centroids[-1]
        return math.hypot(x2 - x1, y2 - y1)

    def velocity(self) -> Tuple[float, float]:
        """Average recent per-frame velocity vector (px/frame)."""
        if len(self._centroids) < 2:
            return (0.0, 0.0)
        (x1, y1) = self._centroids[0]
        (x2, y2) = self._centroids[-1]
        n = len(self._centroids) - 1
        return ((x2 - x1) / n, (y2 - y1) / n)

    # ─────────────────────────────────────────────────────────────
    # PER-FRAME UPDATE (called when a detection matches this track)
    # ─────────────────────────────────────────────────────────────

    def update_geometry(self, bbox: BBox, quality: float, frame_idx: int) -> None:
        """
        Record a new observation for this track: move the box, refresh
        last_seen, and recompute visibility_ratio.

        visibility_ratio = current area / largest area we have ever cleanly
        observed for this track.  When something covers part of the item,
        its detected area shrinks and this ratio drops — which is exactly
        the signal the recognition gate uses to refuse to re-identify.

        We only GROW max_area from reasonably solid detections, and we
        ignore implausible jumps (a merge with an occluder), so the "full
        size" baseline stays honest.
        """
        self.bbox = bbox
        self._centroids.append(self._centroid_of(bbox))
        self.last_seen = frame_idx
        self.prev_visibility_ratio = self.visibility_ratio
        self.observations += 1

        area = float(bbox[2] * bbox[3])
        # Grow the "full visibility" baseline only from clean, plausible obs.
        # The growth cap is the SAME ratio the merge guard uses, so the two
        # cannot disagree: during a track's first few frames (before the merge
        # guard is armed) this is the only thing stopping a union blob from
        # inflating the baseline.  Legitimate growth is not blocked, only
        # rate-limited — the cap is relative to the current max, so an item
        # revealed gradually still reaches its true size over a few frames.
        if quality >= 0.5 and area <= self._max_area * MERGE_AREA_RATIO:
            self._max_area = max(self._max_area, area)
        elif self._max_area <= 1.0:
            self._max_area = area  # first ever observation

        self.visibility_ratio = float(np.clip(area / max(self._max_area, 1.0), 0.0, 1.0))

        # Has this item settled?  Measured from the two most recent observed
        # centroids, so an item that is briefly hidden and reappears somewhere
        # else correctly reads as moving.
        if self.displacement() < MOVING_MIN_DISPLACEMENT:
            self.still_frames += 1
        else:
            self.still_frames = 0

    def visibility_jump(self) -> float:
        """
        Change in visibility since the previous observed frame.

        Large positive = something just stopped covering this item.  On such
        a frame the detected box grows suddenly, so its centroid shifts for
        non-motion reasons and `displacement()` cannot be trusted.
        """
        return self.visibility_ratio - self.prev_visibility_ratio

    def mark_unseen_frame(self) -> None:
        """Called each frame this track was NOT matched to any detection."""
        # Visibility is unknown when unseen; treat as 0 for gating purposes
        # (we will not run recognition), but do NOT touch identity.
        self.prev_visibility_ratio = self.visibility_ratio
        self.visibility_ratio = 0.0

    @property
    def max_observed_area(self) -> float:
        """The largest clean area we have ever measured for this item."""
        return self._max_area

    def note_merged_frame(self, frame_idx: int) -> None:
        """
        A detection matched this track, but it is far too large to be this
        item alone — it is a blob containing this item AND something else.

        We take exactly one thing from it: proof that the item is still
        there.  last_seen is refreshed so the track does not drift toward
        LOST.  Position, size and the max-area baseline are all left alone,
        because measuring them from a merged blob is how a stationary item
        gets dragged toward the exit by its neighbour.
        """
        self.last_seen = frame_idx
        self.prev_visibility_ratio = self.visibility_ratio
        # Not "0" (we can see something) and not high enough to pass the
        # recognition gate — because we genuinely cannot see this item
        # distinctly right now.
        self.visibility_ratio = 0.0
        self.exit_progress = 0

    def frames_unseen(self, frame_idx: int) -> int:
        return frame_idx - self.last_seen

    def note_static_frame(self, frame_idx: int) -> None:
        """
        No detection matched this track, but a direct look at its ROI shows
        the item is still sitting exactly where we left it.

        This is the answer to "the motion detector reports nothing, so is the
        item gone?" for an object that has simply stopped moving.  We refresh
        last_seen so the track does not drift toward LOST, and keep visibility
        high so it is not misread as occluded.

        Geometry is deliberately NOT touched: there is no measured box to move
        to, and the item has not moved anyway.  exit_progress is cleared
        because "it is provably still in place" refutes any evidence that it
        was on its way out.
        """
        self.last_seen = frame_idx
        self.prev_visibility_ratio = self.visibility_ratio
        self.visibility_ratio = 1.0
        self.exit_progress = 0

    # ─────────────────────────────────────────────────────────────
    # STATIC PRESENCE TEMPLATE
    #
    # Used by identity_tracker to answer "is the item still sitting there?"
    # on frames where the motion detector produced no detection for it.
    # Stored at a fixed small size so comparisons are always between
    # equal-size patches and cost well under a millisecond.
    # ─────────────────────────────────────────────────────────────

    def set_presence_template(self, patch: np.ndarray) -> None:
        """
        Remember what this item looks like where it currently sits.

        `patch` is the raw ROI crop from the frame; it is converted to
        grayscale (brightness-invariant matching handles the rest) and
        normalised to a fixed size.  Silently ignores unusable crops rather
        than raising, because a bad crop must never break tracking.
        """
        if patch is None or patch.size == 0:
            return
        if patch.ndim == 3:
            patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        try:
            self.presence_template = cv2.resize(
                patch, (PRESENCE_TEMPLATE_PX, PRESENCE_TEMPLATE_PX),
                interpolation=cv2.INTER_AREA)
        except cv2.error:
            pass

    def has_presence_template(self) -> bool:
        return self.presence_template is not None

    # ─────────────────────────────────────────────────────────────
    # STATE TRANSITIONS  (every one is logged)
    # ─────────────────────────────────────────────────────────────

    def transition(self, new_state: str, frame_idx: int, reason: str = "") -> None:
        if new_state == self.state:
            return
        old = self.state
        self.state = new_state
        self.frames_in_current_state = 0
        self.transitions.append((frame_idx, old, new_state, reason))
        pid = self.product_id if self.product_id else "?"
        print(f"[track {self.track_id:>2} | {pid}] "
              f"{old} -> {new_state}   (frame {frame_idx}"
              f"{'; ' + reason if reason else ''})")

    def tick_state(self) -> None:
        """Advance the in-state frame counter (call once per processed frame)."""
        self.frames_in_current_state += 1

    # ─────────────────────────────────────────────────────────────
    # IDENTITY LOCK  (the irreversible step)
    # ─────────────────────────────────────────────────────────────

    def lock_identity(self, product_id: str, embedding: np.ndarray,
                      confidence: float, frame_idx: int) -> None:
        """
        Set this track's identity ONCE and freeze it forever.

        Refuses to overwrite an already-locked identity.  This is the
        single guarantee the whole design rests on, so we enforce it here
        rather than trusting every caller to be careful.
        """
        if self._locked:
            # Deliberately ignored — re-locking is the bug we are preventing.
            print(f"[track {self.track_id}] lock_identity ignored: already "
                  f"locked to '{self.product_id}' (attempted '{product_id}').")
            return
        self.product_id = product_id
        self.identity_embedding = np.array(embedding, copy=True)  # frozen copy
        self.recognition_confidence = confidence
        self._locked = True
        self.clear_evidence()  # verification evidence has done its job
        self.transition(TrackState.CONFIRMED, frame_idx,
                        reason=f"locked id={product_id} conf={confidence:.2f}")

    @property
    def is_locked(self) -> bool:
        return self._locked

    # ─────────────────────────────────────────────────────────────
    # VERIFICATION EVIDENCE BUFFER  (temporary; gone after CONFIRM)
    # ─────────────────────────────────────────────────────────────

    def add_evidence(self, emb: np.ndarray, result: dict, visibility: float) -> None:
        self.recent_embeddings.append({"emb": emb, "result": result, "vis": visibility})
        if len(self.recent_embeddings) > EVIDENCE_BUFFER_MAX:
            self.recent_embeddings.pop(0)

    def clear_evidence(self) -> None:
        self.recent_embeddings = []

    def evidence_results(self) -> List[dict]:
        return [e["result"] for e in self.recent_embeddings]

    def best_embedding_for(self, product_name: str) -> Optional[np.ndarray]:
        """
        Among buffered evidence that voted for `product_name`, return the
        embedding from the HIGHEST-visibility frame.  This is the clean
        reference vector we lock as identity_embedding — deliberately the
        best view we saw, not the latest one.
        """
        best = None
        best_vis = -1.0
        for e in self.recent_embeddings:
            if e["result"].get("top_name") == product_name and e["vis"] > best_vis:
                best_vis = e["vis"]
                best = e["emb"]
        return best

    # ─────────────────────────────────────────────────────────────
    # CART MEMBERSHIP
    # ─────────────────────────────────────────────────────────────

    def is_counted(self) -> bool:
        """
        True if this track currently contributes its product to the cart.

        Counts once identity is locked, through every state EXCEPT REMOVED.
        This is the literal encoding of "only a confirmed physical exit
        changes cart state".
        """
        return self.product_id is not None and self.state in TrackState.COUNTED

    # ─────────────────────────────────────────────────────────────
    # UI HELPERS
    # ─────────────────────────────────────────────────────────────

    def label(self) -> str:
        if self.product_id:
            return self.product_id.replace("_", " ")
        if self.state == TrackState.VERIFYING:
            return "verifying..."
        return "new"
