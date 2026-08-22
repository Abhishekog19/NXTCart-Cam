# ---------------------------------------------------------------
# ml/detector.py  --  DETECTOR ABSTRACTION
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The whole point of the rebuild is to STOP letting the classifier
# decide, frame by frame, "what" an object is.  Detection should only
# answer a much dumber question:
#
#       "Is there a blob of something here, and where is it?"
#
# It must NEVER answer "what is it" — that is recognition's job, done
# once, later, and then locked.
#
# So this module hides ALL of that behind one tiny interface:
#
#       detections = detector.detect(frame)
#       # -> list of Detection(bbox, mask, quality)
#
# Nothing downstream (tracking, identity locking, occlusion handling,
# the cart reconciler, the UI) is allowed to know or care HOW detection
# happens.  Today it is MOG2 + contours + watershed.  Tomorrow it could
# be a trained YOLO model.  As long as the replacement returns the same
# Detection list, it is a pure drop-in — nothing else changes.
#
# TODAY'S IMPLEMENTATION  (BackgroundSubtractorDetector)
# ───────────────────────────────────────────────────────
#   1. MOG2 background subtraction    -> "something changed" mask
#   2. morphological open/close       -> clean, solid blobs
#   3. external contours              -> candidate regions
#   4. watershed split (big blobs)    -> separate two touching items
#                                        (CHEAP candidate separation, NOT
#                                         guaranteed segmentation — it is
#                                         fine if imperfect for heavily
#                                         overlapping items right now)
#   5. wrap each region as a Detection with a rough 'quality' score
# ---------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from ml.config import (
    BGS_METHOD,
    DET_DT_RATIO,
    DET_LEARNING_RATE,
    DET_MIN_AREA,
    DET_MORPH_KERNEL,
    DET_WARMUP_FRAMES,
    DET_WARMUP_RATE,
    DET_WATERSHED_MIN_AREA,
)

BBox = Tuple[int, int, int, int]  # (x, y, w, h)


# ═════════════════════════════════════════════════════════════════
# THE DATA CONTRACT
# ═════════════════════════════════════════════════════════════════

@dataclass
class Detection:
    """
    One candidate region for one frame.  This is the ONLY thing the
    rest of the system sees coming out of detection.

    Attributes
    ----------
    bbox : (x, y, w, h)
        Axis-aligned bounding box in pixel coordinates.
    mask : np.ndarray or None
        Optional binary mask (uint8 0/255), SAME size as `bbox` (h x w),
        marking which pixels inside the box are foreground.  May be None
        if a detector cannot produce one — downstream must treat it as
        optional.
    quality : float in [0, 1]
        A rough "how clean is this blob" score (solidity-based today).
        This is a DETECTION-level score.  It is NOT the same thing as a
        track's visibility_ratio, which is computed later relative to
        that track's own history.
    """
    bbox: BBox
    mask: Optional[np.ndarray] = None
    quality: float = 1.0

    # ── convenience geometry (never identity!) ────────────────────
    @property
    def area(self) -> int:
        _, _, w, h = self.bbox
        return int(w * h)

    @property
    def centroid(self) -> Tuple[float, float]:
        x, y, w, h = self.bbox
        return (x + w / 2.0, y + h / 2.0)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        """Return the image crop for this detection's bbox (clamped)."""
        H, W = frame.shape[:2]
        x, y, w, h = self.bbox
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(W, x + w); y2 = min(H, y + h)
        return frame[y1:y2, x1:x2]


@runtime_checkable
class Detector(Protocol):
    """
    The swappable interface.  Any object with these two methods can be
    dropped into the tracking pipeline.
    """

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Return the candidate regions found in this frame."""
        ...

    def reset(self) -> None:
        """Forget any accumulated state (e.g. the background model)."""
        ...

    def background_image(self) -> Optional[np.ndarray]:
        """
        The detector's best guess at what the scene looks like with nothing
        in it, or None if it has no such notion.

        Callers MUST handle None: it is a hint, not a guarantee.
        """
        ...


# ═════════════════════════════════════════════════════════════════
# TODAY'S IMPLEMENTATION:  MOG2 + contours + watershed
# ═════════════════════════════════════════════════════════════════

class BackgroundSubtractorDetector:
    """
    Motion-driven candidate detector.

    IMPORTANT MENTAL MODEL:
      MOG2 reports MOTION, not objects.  A freshly placed item shows up
      as foreground while it (and the hand) are moving, then slowly gets
      absorbed into the background once it sits still.  That is fine:
      by then the tracker has already LOCKED the item's identity, and a
      confirmed track deliberately survives having no detection (it goes
      OCCLUDED/LOST, never REMOVED).  Detection's job is only to catch
      items while they are appearing, moving, or leaving.

      That said, absorbing items TOO fast is actively harmful, because the
      next thing that disturbs the scene then produces a partial blob
      (an edge, a sliver) whose centroid has little to do with any real
      item's position — and position is what the exit logic consumes.  So
      the background is learned FAST while the scene is empty at start-up,
      and very SLOWLY afterwards: quick to learn the room, reluctant to
      forget that something was put down in it.
    """

    def __init__(
        self,
        method: str = BGS_METHOD,
        learning_rate: float = DET_LEARNING_RATE,
        min_area: int = DET_MIN_AREA,
        watershed_min_area: int = DET_WATERSHED_MIN_AREA,
        dt_ratio: float = DET_DT_RATIO,
        morph_kernel: int = DET_MORPH_KERNEL,
        warmup_frames: int = DET_WARMUP_FRAMES,
        warmup_rate: float = DET_WARMUP_RATE,
    ) -> None:
        self.method = method
        self.learning_rate = learning_rate
        self.warmup_frames = warmup_frames
        self.warmup_rate = warmup_rate
        self.frames_seen = 0
        self.min_area = min_area
        self.watershed_min_area = watershed_min_area
        self.dt_ratio = dt_ratio
        self._kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel)
        )
        self._bgs = self._make_bgs()

        # Exposed for the UI / debugging only — NOT part of the contract.
        self.last_fg_mask: Optional[np.ndarray] = None
        self.last_fg_pixels: int = 0

    def _make_bgs(self):
        if self.method == "KNN":
            return cv2.createBackgroundSubtractorKNN(detectShadows=True)
        return cv2.createBackgroundSubtractorMOG2(detectShadows=True)

    def reset(self) -> None:
        """Rebuild the background model from scratch."""
        self._bgs = self._make_bgs()
        self.frames_seen = 0
        self.last_fg_mask = None
        self.last_fg_pixels = 0

    def background_image(self) -> Optional[np.ndarray]:
        """
        MOG2's learned model of the empty scene.

        The tracker uses this to ask "does this item's spot now look like bare
        background?" — direct evidence of departure that motion alone cannot
        provide for a stationary object.

        Returns None until the model has matured past warm-up, and swallows
        backend errors, because presence checking is an enhancement: when it
        is unavailable the tracker must fall back to its normal behaviour
        rather than fail.
        """
        if self.frames_seen <= self.warmup_frames:
            return None
        try:
            bg = self._bgs.getBackgroundImage()
        except cv2.error:
            return None
        if bg is None or bg.size == 0:
            return None
        return bg

    # ─────────────────────────────────────────────────────────────
    # PUBLIC:  detect()
    # ─────────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> List[Detection]:
        # ── 1. MOG2 -> raw foreground (motion) ────────────────────
        # Fast learning while the scene is still empty, then slow, so that
        # items which have been put down keep showing up as foreground.
        self.frames_seen += 1
        rate = (self.warmup_rate if self.frames_seen <= self.warmup_frames
                else self.learning_rate)
        fg = self._bgs.apply(frame, learningRate=rate)

        # Keep only DEFINITE foreground.  MOG2 marks shadows as 127;
        # we drop those so a shadow never becomes a phantom item.
        fg_bin = np.where(fg == 255, 255, 0).astype(np.uint8)

        # ── 2. morphological clean-up -> solid blobs ──────────────
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_OPEN, self._kernel)
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_CLOSE, self._kernel)
        # A second, larger close fills interior gaps of a single item.
        big_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_CLOSE, big_close)

        self.last_fg_mask = fg_bin
        self.last_fg_pixels = int(np.count_nonzero(fg_bin))

        # ── 3. external contours -> candidate blobs ───────────────
        contours, _ = cv2.findContours(
            fg_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        detections: List[Detection] = []
        H, W = frame.shape[:2]

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue

            # Single-blob mask for just this contour.
            blob_mask = np.zeros((H, W), dtype=np.uint8)
            cv2.drawContours(blob_mask, [cnt], -1, 255, thickness=cv2.FILLED)

            # ── 4. split touching items (big blobs only) ──────────
            if area >= self.watershed_min_area:
                parts = self._split_touching(frame, blob_mask)
            else:
                x, y, w, h = cv2.boundingRect(cnt)
                parts = [((x, y, w, h), blob_mask)]

            # ── 5. wrap each part as a Detection ──────────────────
            for (bx, by, bw, bh), comp_mask in parts:
                if bw <= 1 or bh <= 1:
                    continue
                sub = comp_mask[by:by + bh, bx:bx + bw]
                region_px = int(np.count_nonzero(sub))
                if region_px < self.min_area * 0.35:
                    continue
                solidity = region_px / float(max(bw * bh, 1))
                quality = float(np.clip(solidity, 0.0, 1.0))
                detections.append(
                    Detection(bbox=(bx, by, bw, bh),
                              mask=sub.copy(),
                              quality=quality)
                )

        return detections

    # ─────────────────────────────────────────────────────────────
    # WATERSHED SPLIT  (cheap candidate separation)
    # ─────────────────────────────────────────────────────────────

    def _split_touching(
        self,
        frame: np.ndarray,
        blob_mask: np.ndarray,
    ) -> List[Tuple[BBox, np.ndarray]]:
        """
        Try to split one big blob into multiple candidate regions using a
        distance-transform + watershed.  Two touching items produce two
        distance peaks -> two seeds -> two labels.

        This is intentionally CHEAP and imperfect: for heavily / fully
        overlapping items it will happily return a single region, and the
        rest of the system is designed to tolerate that (a merged blob
        just means one candidate; identity locking + occlusion handling do
        the heavy lifting).  If watershed finds only one seed, we return
        the blob unchanged.
        """
        dist = cv2.distanceTransform(blob_mask, cv2.DIST_L2, 5)
        peak = float(dist.max())
        if peak <= 0:
            return self._single(blob_mask)

        _, sure_fg = cv2.threshold(dist, self.dt_ratio * peak, 255, 0)
        sure_fg = sure_fg.astype(np.uint8)

        n_labels, seeds = cv2.connectedComponents(sure_fg)
        # n_labels counts the background (label 0) plus one per seed.
        # <= 2 means "background + a single seed" -> only one object.
        if n_labels <= 2:
            return self._single(blob_mask)

        sure_bg = cv2.dilate(blob_mask, self._kernel, iterations=2)
        unknown = cv2.subtract(sure_bg, sure_fg)

        markers = seeds + 1          # shift so background seeds start at 1
        markers[unknown == 255] = 0  # unknown region = 0 for watershed

        # watershed needs a 3-channel uint8 image; `frame` already is.
        markers = cv2.watershed(frame, markers)

        parts: List[Tuple[BBox, np.ndarray]] = []
        for lbl in range(2, int(markers.max()) + 1):
            comp = np.where(markers == lbl, 255, 0).astype(np.uint8)
            if int(np.count_nonzero(comp)) < self.min_area * 0.35:
                continue
            x, y, w, h = cv2.boundingRect(comp)
            parts.append(((x, y, w, h), comp))

        if not parts:
            return self._single(blob_mask)
        return parts

    @staticmethod
    def _single(blob_mask: np.ndarray) -> List[Tuple[BBox, np.ndarray]]:
        x, y, w, h = cv2.boundingRect(blob_mask)
        return [((x, y, w, h), blob_mask)]


# ═════════════════════════════════════════════════════════════════
# TEST DETECTOR:  OracleDetector
# ═════════════════════════════════════════════════════════════════

class OracleDetector:
    """
    A detector that returns exactly the detections it is told to.

    This exists ONLY for the test harness.  Because it implements the same
    Detector interface, we can feed the tracking pipeline perfectly-known
    bounding boxes and thereby test the identity / occlusion / cart logic
    in isolation from MOG2's real-world noise.  (It is also living proof
    that the detector really is a clean, swappable drop-in.)
    """

    def __init__(self) -> None:
        self.pending: List[Detection] = []

    def set(self, detections: List[Detection]) -> None:
        """Queue the detections the next detect() call should return."""
        self.pending = list(detections)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        return list(self.pending)

    def reset(self) -> None:
        self.pending = []

    def background_image(self) -> Optional[np.ndarray]:
        """
        The oracle has no background model — scripted detections are the
        ground truth, so there is nothing to learn and nothing to compare
        against.  Returning None makes the tracker's presence check skip
        itself, which is what we want: the harness must exercise the removal
        state machine on scripted geometry alone.
        """
        return None
