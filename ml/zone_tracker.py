# ---------------------------------------------------------------
# ml/zone_tracker.py
#
# WHAT IT DOES
# ─────────────
# Watches a fixed rectangular "gateway" region of the camera frame.
# When something moves through it, the tracker:
#
#   1. Detects motion using background subtraction (MOG2/KNN).
#      The background model naturally absorbs anything that stops
#      moving after ~1-2 seconds, so a settled item stops producing
#      foreground pixels on its own — no extra "is it still?" logic.
#
#   2. Finds the centroid (centre point) of the foreground blob
#      inside the zone on each active frame.
#
#   3. Builds a short history of centroid positions (last N frames).
#      From the first vs. last position in that history it decides
#      whether the item moved top-to-bottom (ADD) or
#      bottom-to-top (REMOVE).
#
#   4. When motion in the zone drops back to near-zero (object has
#      finished crossing OR fully left), resolves the event:
#        • Picks the best snapshot frame captured during the crossing.
#        • Runs the matcher to identify which product it was.
#        • Fires an on_event callback: ("ADD"/"REMOVE", product_name)
#        • Starts a cooldown so the same slow movement isn't double-counted.
#
# DESIGN DECISION — why centroid direction, not pixel-region toggle?
# ────────────────────────────────────────────────────────────────────
# A toggle approach simply checks whether foreground pixels exist inside
# the zone, then flips state.  It can't tell the difference between an
# item being placed IN vs. being lifted OUT.  Tracking the centroid's
# movement direction through the zone gives us that information directly.
#
# HOW TO USE
# ──────────
#   tracker = ZoneTracker(on_event=my_callback, db=embedding_db)
#   for each frame:
#       display_frame = tracker.process(frame)
# ---------------------------------------------------------------

import time
import threading
from collections import deque
from typing import Callable, Optional

import cv2
import numpy as np

from ml.config import (
    BGS_LEARNING_RATE,
    BGS_METHOD,
    CENTROID_HISTORY_LEN,
    ENTRY_Y_FRACTION,
    EVENT_COOLDOWN_SEC,
    FG_PIXEL_THRESHOLD,
    MAX_SNAPSHOTS,
    ZONE_RECT,
)
from ml.embedding_extractor import extract_embedding
from ml.matcher import EmbeddingDB, match


# Maximum number of snapshots to actually run inference on.
# We pick them evenly spaced from the full snapshot buffer.
# 3 snapshots × ~80ms each = ~240ms total — keeps the UI responsive.
_MAX_INFERENCE_SNAPS = 3


# ── Internal state machine states ────────────────────────────────
class _State:
    IDLE     = "idle"      # No motion in zone
    TRACKING = "tracking"  # Motion detected, collecting centroid history
    COOLDOWN = "cooldown"  # Just resolved an event, ignoring briefly


class ZoneTracker:
    """
    Detects items crossing a zone rectangle and fires ADD/REMOVE events.

    Parameters
    ----------
    on_event : callable(direction: str, product_name: str, score: float)
        Called once per resolved crossing event.
        direction is "ADD" or "REMOVE".
        product_name is the matched product, or "unknown" if unconfident.
        score is the cosine similarity (0-1) of the best match.

    db : EmbeddingDB, optional
        Pre-loaded embedding database.  If None, loaded from disk.

    zone_rect : tuple (x, y, w, h), optional
        Override the zone rectangle from config.py.  Useful for tests.
    """

    def __init__(
        self,
        on_event: Callable[[str, str, float], None],
        db: Optional[EmbeddingDB] = None,
        zone_rect: Optional[tuple] = None,
    ) -> None:
        self.on_event = on_event
        self.db = db
        self.zone_rect = zone_rect or ZONE_RECT   # (x, y, w, h)

        # ── Background subtractor ─────────────────────────────────
        if BGS_METHOD == "KNN":
            self._bgs = cv2.createBackgroundSubtractorKNN(
                detectShadows=True
            )
        else:
            self._bgs = cv2.createBackgroundSubtractorMOG2(
                detectShadows=True
            )

        # ── Centroid history ──────────────────────────────────────
        self._centroids: deque = deque(maxlen=CENTROID_HISTORY_LEN)

        # ── Snapshot buffer ───────────────────────────────────────
        self._snapshots: list[np.ndarray] = []

        # ── State machine ─────────────────────────────────────────
        self._state = _State.IDLE
        self._cooldown_until = 0.0

        # ── Background identification thread ──────────────────────
        # Identification (embedding + matching) runs in a separate
        # thread so the camera loop is never blocked.
        self._id_thread: Optional[threading.Thread] = None
        self._identifying = False     # True while the thread is running

        # ── For the UI overlay ────────────────────────────────────
        self.ui_state  = "idle"
        self.ui_direction = "--"
        self.ui_fg_pixels = 0
        self.last_event: Optional[dict] = None

    # ── Public API ────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Process one camera frame.

        Returns the frame with debug visualisations drawn on it.
        Never blocks: identification runs in a background thread.
        """
        x, y, w, h = self.zone_rect
        now = time.time()

        # ── Step 1: crop to zone ──────────────────────────────────
        zone_crop = frame[y : y + h, x : x + w]

        # ── Step 2: apply background subtractor to the crop ───────
        fg_mask = self._bgs.apply(
            zone_crop, learningRate=BGS_LEARNING_RATE
        )

        # Keep only definite foreground (value == 255), drop shadows.
        fg_binary = (fg_mask == 255).astype(np.uint8) * 255

        # ── Step 3: morphological cleanup ────────────────────────
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_OPEN, kernel)
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_CLOSE, kernel)

        # ── Step 4: count active foreground pixels ────────────────
        fg_count = int(np.sum(fg_binary > 0))
        self.ui_fg_pixels = fg_count
        active = fg_count >= FG_PIXEL_THRESHOLD

        # ── Step 5: find centroid if active ───────────────────────
        centroid_rel: Optional[tuple[float, float]] = None
        if active:
            M = cv2.moments(fg_binary)
            if M["m00"] > 0:
                cx_abs = M["m10"] / M["m00"]
                cy_abs = M["m01"] / M["m00"]
                centroid_rel = (cx_abs / w, cy_abs / h)

        # ── Step 6: state machine ─────────────────────────────────
        if self._state == _State.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = _State.IDLE
                self.ui_state = "idle"

        elif self._state == _State.IDLE:
            if active and centroid_rel is not None:
                self._state = _State.TRACKING
                self._centroids.clear()
                self._snapshots.clear()
                self._centroids.append(centroid_rel)
                self._snapshots.append(frame.copy())
                self.ui_state = "tracking"
                self._update_direction_ui()

        elif self._state == _State.TRACKING:
            if active and centroid_rel is not None:
                self._centroids.append(centroid_rel)
                if len(self._snapshots) < MAX_SNAPSHOTS:
                    self._snapshots.append(frame.copy())
                self._update_direction_ui()

            else:
                # Motion stopped — resolve event in background thread.
                if len(self._centroids) >= 3:
                    self._start_identification()
                # Transition immediately so the UI stays responsive.
                self._state = _State.COOLDOWN
                self._cooldown_until = now + EVENT_COOLDOWN_SEC
                self._centroids.clear()
                self._snapshots.clear()
                self.ui_state = "cooldown"
                self.ui_direction = "--"

        # ── Step 7: draw visuals on the frame ────────────────────
        vis = self._draw(frame, fg_binary, centroid_rel, x, y, w, h)
        return vis

    # ── Private helpers ───────────────────────────────────────────

    def _update_direction_ui(self) -> None:
        """Infer current travel direction from centroid history."""
        if len(self._centroids) < 2:
            self.ui_direction = "--"
            return
        first_y = self._centroids[0][1]
        last_y  = self._centroids[-1][1]
        dy = last_y - first_y
        if abs(dy) < 0.05:
            self.ui_direction = "lateral"
        elif dy > 0:
            self.ui_direction = "inward"
        else:
            self.ui_direction = "outward"

    def _decide_direction(self, centroids: list) -> Optional[str]:
        """
        Decide ADD or REMOVE from centroid history.

        Returns "ADD", "REMOVE", or None (ambiguous).
        """
        if len(centroids) < 2:
            return None

        first_cy = centroids[0][1]
        last_cy  = centroids[-1][1]

        above = lambda cy: cy < ENTRY_Y_FRACTION
        below = lambda cy: cy >= ENTRY_Y_FRACTION

        if above(first_cy) and below(last_cy):
            return "ADD"
        if below(first_cy) and above(last_cy):
            return "REMOVE"
        return None

    def _start_identification(self) -> None:
        """
        Kick off product identification in a background thread.

        Takes a snapshot of the current centroids and snapshots,
        clears the buffers, and starts the thread.  The main loop
        continues rendering frames without any pause.
        """
        # Don't start a new thread if one is still running.
        if self._identifying:
            return

        # Copy what we need — the buffers will be cleared by the caller.
        centroids_copy = list(self._centroids)
        snapshots_copy = list(self._snapshots)

        self._identifying = True
        self.ui_state = "identifying"

        self._id_thread = threading.Thread(
            target=self._resolve_event_threaded,
            args=(centroids_copy, snapshots_copy),
            daemon=True,
        )
        self._id_thread.start()

    def _resolve_event_threaded(
        self,
        centroids: list,
        snapshots: list[np.ndarray],
    ) -> None:
        """
        Runs in a background thread.  Identifies the product from
        snapshots and fires the on_event callback.
        """
        try:
            direction = self._decide_direction(centroids)
            if direction is None:
                return

            product_name = "unknown"
            score        = 0.0

            if snapshots and self.db is not None:
                # Pick at most _MAX_INFERENCE_SNAPS evenly-spaced frames.
                # E.g. if we have 6 snapshots and want 3, pick indices [0, 3, 5].
                n = len(snapshots)
                if n <= _MAX_INFERENCE_SNAPS:
                    chosen = snapshots
                else:
                    indices = [
                        int(i * (n - 1) / (_MAX_INFERENCE_SNAPS - 1))
                        for i in range(_MAX_INFERENCE_SNAPS)
                    ]
                    chosen = [snapshots[i] for i in indices]

                best_score = -1.0
                best_name  = "unknown"

                for snap in chosen:
                    try:
                        emb    = extract_embedding(snap)
                        result = match(emb, db=self.db)

                        if result["top_score"] > best_score:
                            best_score = result["top_score"]
                            best_name  = result["top_name"]

                    except Exception as e:
                        print(f"[zone_tracker] Snapshot match error: {e}")

                if best_score > 0:
                    product_name = best_name
                    score = best_score

            elif snapshots and self.db is None:
                product_name = "no_db"

            # ── Fire callback ─────────────────────────────────────
            event = {
                "direction":    direction,
                "product_name": product_name,
                "score":        round(score, 4),
                "timestamp":    time.time(),
            }
            self.last_event = event
            print(
                f"[zone_tracker] EVENT: {direction}  product={product_name}"
                f"  score={score:.3f}"
            )
            self.on_event(direction, product_name, score)

        finally:
            self._identifying = False
            # Don't reset ui_state here — the main loop manages that.

    def _draw(
        self,
        frame: np.ndarray,
        fg_binary: np.ndarray,
        centroid_rel: Optional[tuple],
        x: int, y: int, w: int, h: int,
    ) -> np.ndarray:
        """
        Draw the zone rectangle, centroid dot, direction arrow, and
        state label onto the frame for live visualisation.
        """
        out = frame.copy()

        # ── Zone rectangle colour based on state ─────────────────
        state_colors = {
            _State.IDLE:     (0,   200,  0),   # green
            _State.TRACKING: (0,   200, 255),  # yellow
            _State.COOLDOWN: (180, 180, 180),  # grey
        }
        rect_color = state_colors.get(self._state, (255, 255, 255))
        cv2.rectangle(out, (x, y), (x + w, y + h), rect_color, 2)

        # ── Zone state label (top-left of zone) ───────────────────
        label = f"{self._state}  dir:{self.ui_direction}"
        cv2.putText(
            out, label,
            (x + 4, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, rect_color, 1, cv2.LINE_AA
        )

        # ── Foreground pixel count (bottom-left of zone) ──────────
        cv2.putText(
            out, f"fg:{self.ui_fg_pixels}",
            (x + 4, y + h - 6),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, rect_color, 1, cv2.LINE_AA
        )

        # ── Centroid dot ──────────────────────────────────────────
        if centroid_rel is not None:
            cx_abs = int(centroid_rel[0] * w) + x
            cy_abs = int(centroid_rel[1] * h) + y
            cv2.circle(out, (cx_abs, cy_abs), 6, (0, 0, 255), -1)   # filled red dot
            cv2.circle(out, (cx_abs, cy_abs), 8, (255, 255, 255), 1) # white ring

        # ── Direction dividing line ───────────────────────────────
        # Show the ADD/REMOVE boundary visually.
        div_y = int(y + h * ENTRY_Y_FRACTION)
        cv2.line(out, (x, div_y), (x + w, div_y), (0, 255, 200), 1)
        cv2.putText(
            out, "ADD \u2193 | REMOVE \u2191",
            (x + 4, div_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 200), 1, cv2.LINE_AA
        )

        # ── Small foreground mask inset (top-right corner) ────────
        # Shows what the background subtractor actually sees inside
        # the zone — extremely useful for tuning FG_PIXEL_THRESHOLD.
        try:
            inset_size = (w // 3, h // 3)
            fg_inset = cv2.resize(fg_binary, inset_size)
            fg_inset_bgr = cv2.cvtColor(fg_inset, cv2.COLOR_GRAY2BGR)
            ix = x + w - inset_size[0] - 2
            iy = y + 2
            out[iy : iy + inset_size[1], ix : ix + inset_size[0]] = fg_inset_bgr
        except Exception:
            pass  # silently skip if size mismatch on small frames

        return out
