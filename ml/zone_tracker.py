# ---------------------------------------------------------------
# ml/zone_tracker.py
#
# FULL-FRAME CART TRACKER
# ────────────────────────
# The whole camera frame is treated as the cart surface.
# No gateway rectangle needed — just point the camera at the surface
# where products will be placed and removed.
#
# HOW ADD DETECTION WORKS
# ────────────────────────
# 1. Motion appears (object enters frame or is placed down).
# 2. We track the centroid of the moving blob.
# 3. Motion stops and the blob settled INSIDE the frame (not at an edge).
# 4. We wait SETTLE_WAIT_SEC to let autofocus settle and movement fully stop.
# 5. We grab ADD_SETTLE_FRAMES clean, still frames of the resting item.
# 6. Scan those still frames against the FULL product database.
#    Still frames = much clearer photos = better match accuracy.
#
# HOW REMOVE DETECTION WORKS
# ───────────────────────────
# 1. Motion appears (hand grabs a resting item).
# 2. We track the centroid moving toward the frame edge.
# 3. The blob disappears at or near the frame edge (item left the frame).
# 4. Scan the motion frames (captured while item was still visible) against
#    ONLY the items currently in the cart — NOT the full database.
#    This is faster (fewer comparisons) and more accurate (we know what
#    should be in the cart; we just need to identify which one left).
#
# DIRECTION LOGIC
# ────────────────
# - EDGE ZONE: outer EDGE_MARGIN_FRACTION of the frame (each side).
# - If motion STOPS and last centroid is NOT in the edge zone → ADD candidate.
# - If motion STOPS and last centroid IS in the edge zone → REMOVE.
#   (The blob reached the edge and disappeared there.)
# ---------------------------------------------------------------

import time
import threading
from collections import deque
from typing import Callable, Optional

import cv2
import numpy as np

from ml.config import (
    ADD_SETTLE_FRAMES,
    BGS_LEARNING_RATE,
    BGS_METHOD,
    CENTROID_HISTORY_LEN,
    EDGE_MARGIN_FRACTION,
    EVENT_COOLDOWN_SEC,
    FG_PIXEL_THRESHOLD,
    MAX_SNAPSHOTS,
    REMOVE_MOTION_FRAMES,
    SCORE_THRESHOLD,
    SETTLE_WAIT_SEC,
)
from ml.embedding_extractor import extract_embedding
from ml.matcher import EmbeddingDB, match


# How many frames (at most) to run inference on.
# Runs in a background thread, so 3 frames × ~80ms = ~240ms off the UI thread.
_MAX_INFERENCE_SNAPS = 3


class _State:
    IDLE     = "idle"      # Waiting for motion
    TRACKING = "tracking"  # Motion detected, accumulating centroid + frames
    SETTLING = "settling"  # Motion stopped inside frame, waiting before ADD scan
    COOLDOWN = "cooldown"  # Just fired event, ignoring briefly


class ZoneTracker:
    """
    Full-frame cart tracker using background subtraction + centroid direction.

    Parameters
    ----------
    on_event : callable(direction: str, product_name: str, score: float)
        Called once per resolved event.
        direction is "ADD" or "REMOVE".

    db : EmbeddingDB, optional
        Full product database — used for ADD matching.

    get_cart_db : callable() -> EmbeddingDB, optional
        Called at REMOVE time to get a database containing ONLY the items
        currently in the cart.  This makes REMOVE matching faster and more
        targeted.  If None, the full db is used for REMOVE too.

    frame_size : (width, height)
        Camera frame dimensions.  Used to compute pixel coordinates of
        the edge margin boundary.
    """

    def __init__(
        self,
        on_event: Callable[[str, str, float], None],
        db: Optional[EmbeddingDB] = None,
        get_cart_db: Optional[Callable[[], Optional[EmbeddingDB]]] = None,
        frame_size: tuple = (640, 480),
    ) -> None:
        self.on_event    = on_event
        self.db          = db
        self.get_cart_db = get_cart_db
        self.frame_w, self.frame_h = frame_size

        # ── Background subtractor ─────────────────────────────────
        # Runs on the FULL frame — no zone cropping needed.
        if BGS_METHOD == "KNN":
            self._bgs = cv2.createBackgroundSubtractorKNN(detectShadows=True)
        else:
            self._bgs = cv2.createBackgroundSubtractorMOG2(detectShadows=True)

        # ── Tracking buffers ──────────────────────────────────────
        self._centroids: deque = deque(maxlen=CENTROID_HISTORY_LEN)
        self._motion_snaps: list[np.ndarray] = []  # frames captured during motion
        self._settle_snaps: list[np.ndarray] = []  # frames captured while settled

        # ── State machine ─────────────────────────────────────────
        self._state          = _State.IDLE
        self._cooldown_until = 0.0
        self._settle_start   = 0.0   # when SETTLING began

        # ── Background thread ────────────────────────────────────
        self._id_thread: Optional[threading.Thread] = None
        self._identifying = False

        # ── UI fields (read by live_cart_demo.py each frame) ──────
        self.ui_state     = "idle"
        self.ui_direction = "--"
        self.ui_fg_pixels = 0
        self.last_event: Optional[dict] = None

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Process one camera frame.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR frame from the camera.

        Returns
        -------
        np.ndarray
            The frame with overlay visualisations drawn on it.
            Never blocks — identification runs in a background thread.
        """
        now = time.time()
        H, W = frame.shape[:2]

        # ── Step 1: background subtraction on FULL frame ──────────
        fg_mask   = self._bgs.apply(frame, learningRate=BGS_LEARNING_RATE)
        # Keep only definite foreground (255); drop shadows (127).
        fg_binary = (fg_mask == 255).astype(np.uint8) * 255

        # ── Step 2: morphological cleanup ────────────────────────
        # Opening removes noise speckles; Closing fills blob holes.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_OPEN,  k)
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_CLOSE, k)

        # ── Step 3: foreground pixel count ───────────────────────
        fg_count        = int(np.sum(fg_binary > 0))
        self.ui_fg_pixels = fg_count
        active          = fg_count >= FG_PIXEL_THRESHOLD

        # ── Step 4: centroid of the moving blob ──────────────────
        centroid_rel: Optional[tuple] = None
        if active:
            M = cv2.moments(fg_binary)
            if M["m00"] > 0:
                # Store as fractions [0,1] of frame size so the logic
                # doesn't depend on the actual resolution.
                cx = M["m10"] / M["m00"] / W
                cy = M["m01"] / M["m00"] / H
                centroid_rel = (cx, cy)

        # ── Step 5: state machine ─────────────────────────────────
        if self._state == _State.COOLDOWN:
            if now >= self._cooldown_until:
                self._state   = _State.IDLE
                self.ui_state = "idle"

        elif self._state == _State.IDLE:
            if active and centroid_rel:
                # Motion started — begin tracking.
                self._state = _State.TRACKING
                self._centroids.clear()
                self._motion_snaps.clear()
                self._settle_snaps.clear()
                self._centroids.append(centroid_rel)
                self._motion_snaps.append(frame.copy())
                self.ui_state = "tracking"
                self._update_direction_ui()

        elif self._state == _State.TRACKING:
            if active and centroid_rel:
                # Still moving — accumulate.
                self._centroids.append(centroid_rel)
                if len(self._motion_snaps) < MAX_SNAPSHOTS:
                    self._motion_snaps.append(frame.copy())
                self._update_direction_ui()

            else:
                # Motion stopped.  Was the item moving toward the edge (REMOVE)
                # or did it settle inside the frame (ADD)?
                if len(self._centroids) >= 2:
                    last_c = self._centroids[-1]
                    if self._near_edge(last_c):
                        # Blob disappeared at the frame edge → REMOVE
                        snaps = self._motion_snaps[-REMOVE_MOTION_FRAMES:] or [frame.copy()]
                        self._fire_identification("REMOVE", snaps)
                        self._enter_cooldown(now)
                    else:
                        # Blob stopped inside frame → ADD (wait for settling)
                        self._state       = _State.SETTLING
                        self._settle_start = now
                        self._settle_snaps.clear()
                        self.ui_state     = "settling"
                        # Don't clear motion snaps yet; settle snaps will replace them.
                else:
                    # Too brief — ignore.
                    self._enter_cooldown(now)

                self._centroids.clear()
                self._motion_snaps.clear()
                self.ui_direction = "--"

        elif self._state == _State.SETTLING:
            if active:
                # Motion restarted before settling finished.
                # This could be the user adjusting the item or picking it back up.
                # Reset to TRACKING so we can re-evaluate.
                self._state = _State.TRACKING
                self._centroids.clear()
                self._settle_snaps.clear()
                self._motion_snaps.clear()
                if centroid_rel:
                    self._centroids.append(centroid_rel)
                    self._motion_snaps.append(frame.copy())
                self.ui_state = "tracking"
                self._update_direction_ui()
            else:
                # Still settled — collect clean still frames for scanning.
                if len(self._settle_snaps) < ADD_SETTLE_FRAMES:
                    self._settle_snaps.append(frame.copy())

                # After settle period expires, scan the still frames.
                if now - self._settle_start >= SETTLE_WAIT_SEC:
                    snaps = self._settle_snaps if self._settle_snaps else [frame.copy()]
                    self._fire_identification("ADD", snaps)
                    self._settle_snaps.clear()
                    self._enter_cooldown(now)

        # ── Step 6: draw overlay ──────────────────────────────────
        return self._draw(frame, fg_binary, centroid_rel)

    # ─────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _near_edge(self, centroid_rel: tuple) -> bool:
        """
        Return True if the centroid is within EDGE_MARGIN_FRACTION of
        any frame edge (top, bottom, left, right).
        """
        cx, cy = centroid_rel
        m = EDGE_MARGIN_FRACTION
        return cx < m or cx > (1 - m) or cy < m or cy > (1 - m)

    def _enter_cooldown(self, now: float) -> None:
        self._state          = _State.COOLDOWN
        self._cooldown_until = now + EVENT_COOLDOWN_SEC
        self.ui_state        = "cooldown"

    def _update_direction_ui(self) -> None:
        """Update the ui_direction label from centroid history."""
        if len(self._centroids) < 2:
            self.ui_direction = "--"
            return
        first = self._centroids[0]
        last  = self._centroids[-1]
        dx = last[0] - first[0]
        dy = last[1] - first[1]
        dist = (dx**2 + dy**2) ** 0.5
        if dist < 0.03:
            self.ui_direction = "stationary"
        elif abs(dx) >= abs(dy):
            self.ui_direction = "right" if dx > 0 else "left"
        else:
            self.ui_direction = "down" if dy > 0 else "up"

    def _fire_identification(
        self,
        direction: str,
        snapshots: list[np.ndarray],
    ) -> None:
        """
        Launch product identification in a background thread.

        direction : "ADD" or "REMOVE"
        snapshots : frames to run inference on
        """
        if self._identifying:
            return  # previous thread still running — skip

        self._identifying = True
        self.ui_state     = "identifying"

        self._id_thread = threading.Thread(
            target=self._identify_threaded,
            args=(direction, snapshots),
            daemon=True,
        )
        self._id_thread.start()

    def _identify_threaded(
        self,
        direction: str,
        snapshots: list[np.ndarray],
    ) -> None:
        """
        Runs in a background thread.

        ADD:    match against the full product database.
        REMOVE: match only against items already in the cart.
                This is faster (fewer products to compare) and
                makes more sense — we can only remove something that's there.
        """
        try:
            # ── Choose which database to search ──────────────────
            if direction == "REMOVE" and self.get_cart_db is not None:
                db = self.get_cart_db()
                if not db:
                    # Cart is empty — can't remove anything.
                    print("[zone_tracker] REMOVE ignored: cart is empty.")
                    return
            else:
                db = self.db

            if not db or not snapshots:
                return

            # ── Pick evenly-spaced frames to infer on ────────────
            n = len(snapshots)
            k = min(_MAX_INFERENCE_SNAPS, n)
            if k == n:
                chosen = snapshots
            else:
                indices = [int(i * (n - 1) / (k - 1)) for i in range(k)]
                chosen  = [snapshots[i] for i in indices]

            best_score = -1.0
            best_name  = "unknown"

            for snap in chosen:
                try:
                    emb    = extract_embedding(snap)
                    result = match(emb, db=db)
                    if result["top_score"] > best_score:
                        best_score = result["top_score"]
                        best_name  = result["top_name"]
                except Exception as e:
                    print(f"[zone_tracker] Inference error: {e}")

            # Only fire event if we got a meaningful score.
            if best_score < SCORE_THRESHOLD:
                print(
                    f"[zone_tracker] {direction} below threshold "
                    f"(score={best_score:.3f} < {SCORE_THRESHOLD}) — ignored."
                )
                return

            event = {
                "direction":    direction,
                "product_name": best_name,
                "score":        round(best_score, 4),
                "timestamp":    time.time(),
            }
            self.last_event = event
            print(
                f"[zone_tracker] EVENT: {direction}  "
                f"product={best_name}  score={best_score:.3f}"
            )
            self.on_event(direction, best_name, best_score)

        finally:
            self._identifying = False

    # ─────────────────────────────────────────────────────────────
    # DRAWING
    # ─────────────────────────────────────────────────────────────

    def _draw(
        self,
        frame: np.ndarray,
        fg_binary: np.ndarray,
        centroid_rel: Optional[tuple],
    ) -> np.ndarray:
        """
        Draw overlays on the frame:
          - Dashed inner rectangle showing the ADD interior zone
          - Centroid dot (red) when motion is detected
          - State label + fg count
          - Settling progress bar
          - Small FG mask inset (top-right) for debugging
        """
        out = frame.copy()
        W, H = self.frame_w, self.frame_h
        m = EDGE_MARGIN_FRACTION

        # ── Edge margin rectangle ─────────────────────────────────
        # Items inside this rectangle when they stop → ADD.
        # Items that exit this region (last centroid outside) → REMOVE.
        ex1 = int(W * m)
        ey1 = int(H * m)
        ex2 = int(W * (1 - m))
        ey2 = int(H * (1 - m))

        state_color = {
            _State.IDLE:     (0,   200,   0),   # green
            _State.TRACKING: (0,   200, 255),   # yellow
            _State.SETTLING: (0,   180, 100),   # teal
            _State.COOLDOWN: (150, 150, 150),   # grey
        }.get(self._state, (255, 255, 255))

        # Outer frame border
        cv2.rectangle(out, (2, 2), (W - 3, H - 3), (60, 60, 70), 1)
        # Inner "ADD zone" rectangle
        cv2.rectangle(out, (ex1, ey1), (ex2, ey2), state_color, 2)

        # Corner labels
        cv2.putText(out, "REMOVE zone",
                    (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 80, 90), 1, cv2.LINE_AA)
        cv2.putText(out, "ADD zone",
                    (ex1 + 4, ey1 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, state_color, 1, cv2.LINE_AA)

        # ── State + direction label ───────────────────────────────
        label = "%s  dir:%s" % (self._state, self.ui_direction)
        cv2.putText(out, label,
                    (ex1 + 4, ey1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, state_color, 1, cv2.LINE_AA)

        # ── FG pixel count (bottom-left) ──────────────────────────
        cv2.putText(out, "fg:%d" % self.ui_fg_pixels,
                    (4, H - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (100, 100, 110), 1, cv2.LINE_AA)

        # ── Centroid dot ──────────────────────────────────────────
        if centroid_rel is not None:
            cx_abs = int(centroid_rel[0] * W)
            cy_abs = int(centroid_rel[1] * H)
            cv2.circle(out, (cx_abs, cy_abs), 7, (0,   0,   255), -1)   # red filled
            cv2.circle(out, (cx_abs, cy_abs), 9, (255, 255, 255),  1)   # white ring

        # ── Settling progress bar ─────────────────────────────────
        # Shows how close we are to firing the ADD scan.
        if self._state == _State.SETTLING:
            elapsed = time.time() - self._settle_start
            ratio   = min(1.0, elapsed / SETTLE_WAIT_SEC)
            bar_x1  = ex1
            bar_x2  = ex1 + int((ex2 - ex1) * ratio)
            bar_y   = ey2 + 6
            cv2.rectangle(out, (ex1, bar_y),
                          (ex2, bar_y + 8), (40, 60, 40), -1)   # track
            cv2.rectangle(out, (bar_x1, bar_y),
                          (bar_x2, bar_y + 8), (0, 210, 100), -1) # fill
            cv2.putText(out, "Settling... hold still",
                        (ex1 + 4, bar_y + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 210, 100), 1, cv2.LINE_AA)

        # ── Tiny FG mask inset (top-right) ────────────────────────
        # Helps you see exactly what the background subtractor sees.
        try:
            inset_w = W // 5
            inset_h = H // 5
            inset   = cv2.resize(fg_binary, (inset_w, inset_h))
            inset   = cv2.cvtColor(inset, cv2.COLOR_GRAY2BGR)
            out[4 : 4 + inset_h, W - inset_w - 4 : W - 4] = inset
        except Exception:
            pass

        return out
