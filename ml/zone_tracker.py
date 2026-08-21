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
        # We restrict it to the zone crop only (not the full frame),
        # so irrelevant motion outside the zone is completely ignored.
        if BGS_METHOD == "KNN":
            self._bgs = cv2.createBackgroundSubtractorKNN(
                detectShadows=True
            )
        else:
            self._bgs = cv2.createBackgroundSubtractorMOG2(
                detectShadows=True   # mark shadows as 127, not 255
            )

        # ── Centroid history ──────────────────────────────────────
        # A deque (double-ended queue) keeps only the last N positions.
        # When it's full, the oldest is automatically dropped.
        # Each entry: (cx_relative, cy_relative) — coordinates
        # expressed as fractions of the zone width/height, so the
        # decision logic doesn't depend on absolute pixel values.
        self._centroids: deque = deque(maxlen=CENTROID_HISTORY_LEN)

        # ── Snapshot buffer ───────────────────────────────────────
        # Raw BGR frames captured while motion is active.
        # We'll pick the best one for product matching after the event.
        self._snapshots: list[np.ndarray] = []

        # ── State machine ─────────────────────────────────────────
        self._state = _State.IDLE
        self._cooldown_until = 0.0   # epoch time when cooldown expires

        # ── For the UI overlay ────────────────────────────────────
        # These are set so live_cart_demo.py can read them each frame.
        self.ui_state  = "idle"        # human-readable state
        self.ui_direction = "—"        # "inward", "outward", or "—"
        self.ui_fg_pixels = 0          # count of active foreground pixels
        self.last_event: Optional[dict] = None  # last resolved event dict

    # ── Public API ────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Process one camera frame.

        Returns the frame with debug visualisations drawn on it
        (zone rectangle, centroid dot, state text).
        This is what live_cart_demo.py should display.
        """
        x, y, w, h = self.zone_rect
        now = time.time()

        # ── Step 1: crop to zone ──────────────────────────────────
        # Extract just the zone region from the full frame.
        # All subsequent processing works on this small crop.
        zone_crop = frame[y : y + h, x : x + w]

        # ── Step 2: apply background subtractor to the crop ───────
        # apply() returns a "foreground mask": white (255) where
        # pixels differ from the learned background, black (0) where
        # they match.  Shadows are grey (127); we treat them as bg.
        fg_mask = self._bgs.apply(
            zone_crop, learningRate=BGS_LEARNING_RATE
        )

        # Keep only definite foreground (value == 255), drop shadows.
        fg_binary = (fg_mask == 255).astype(np.uint8) * 255

        # ── Step 3: morphological cleanup ────────────────────────
        # "Opening" (erode then dilate) removes tiny noise specks.
        # "Closing" fills small holes in the foreground blob.
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
            # Moments are weighted sums of pixel positions.
            # M["m00"] = area, M["m10"]/M["m00"] = x centroid, etc.
            M = cv2.moments(fg_binary)
            if M["m00"] > 0:
                cx_abs = M["m10"] / M["m00"]   # centroid x in crop coords
                cy_abs = M["m01"] / M["m00"]   # centroid y in crop coords
                # Convert to fractions [0, 1] of zone size.
                centroid_rel = (cx_abs / w, cy_abs / h)

        # ── Step 6: state machine ─────────────────────────────────
        if self._state == _State.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = _State.IDLE
                self.ui_state = "idle"
            # During cooldown: still show video, do nothing else.

        elif self._state == _State.IDLE:
            if active and centroid_rel is not None:
                # Motion started → begin tracking.
                self._state = _State.TRACKING
                self._centroids.clear()
                self._snapshots.clear()
                self._centroids.append(centroid_rel)
                self._snapshots.append(frame.copy())
                self.ui_state = "tracking"
                self._update_direction_ui()

        elif self._state == _State.TRACKING:
            if active and centroid_rel is not None:
                # Still moving — accumulate data.
                self._centroids.append(centroid_rel)
                if len(self._snapshots) < MAX_SNAPSHOTS:
                    self._snapshots.append(frame.copy())
                self._update_direction_ui()

            else:
                # Motion stopped (or object fully left zone).
                # Resolve the event if we have enough centroid history.
                if len(self._centroids) >= 3:
                    self._resolve_event()
                else:
                    # Too brief to be reliable — ignore.
                    pass

                self._state = _State.COOLDOWN
                self._cooldown_until = now + EVENT_COOLDOWN_SEC
                self._centroids.clear()
                self._snapshots.clear()
                self.ui_state = "cooldown"
                self.ui_direction = "—"

        # ── Step 7: draw visuals on the frame ────────────────────
        vis = self._draw(frame, fg_binary, centroid_rel, x, y, w, h)
        return vis

    # ── Private helpers ───────────────────────────────────────────

    def _update_direction_ui(self) -> None:
        """
        Infer current travel direction from centroid history and update
        the ui_direction string for the live display.
        """
        if len(self._centroids) < 2:
            self.ui_direction = "—"
            return
        first_y = self._centroids[0][1]   # y-fraction at start
        last_y  = self._centroids[-1][1]  # y-fraction now
        dy = last_y - first_y
        if abs(dy) < 0.05:               # centroid barely moved vertically
            self.ui_direction = "lateral"
        elif dy > 0:
            self.ui_direction = "inward"  # moving down (toward bottom of zone)
        else:
            self.ui_direction = "outward" # moving up (toward top of zone)

    def _decide_direction(self) -> Optional[str]:
        """
        Look at the full centroid history and decide ADD or REMOVE.

        Returns "ADD", "REMOVE", or None (ambiguous).

        Decision rule:
            first centroid is in the TOP band  and
            last  centroid is in the BOTTOM band  → ADD  (item going in)

            first centroid is in the BOTTOM band and
            last  centroid is in the TOP band     → REMOVE (item coming out)

            anything else → ambiguous (lateral movement, jitter, etc.)

        The band boundary is ENTRY_Y_FRACTION of the zone height.
        """
        if len(self._centroids) < 2:
            return None

        first_cy = self._centroids[0][1]   # relative y at start (0 = top, 1 = bottom)
        last_cy  = self._centroids[-1][1]  # relative y at end

        above = lambda cy: cy < ENTRY_Y_FRACTION
        below = lambda cy: cy >= ENTRY_Y_FRACTION

        if above(first_cy) and below(last_cy):
            return "ADD"
        if below(first_cy) and above(last_cy):
            return "REMOVE"
        return None   # didn't cross the midline cleanly

    def _resolve_event(self) -> None:
        """
        Called once the crossing is complete.

        1. Decide direction (ADD/REMOVE).
        2. Pick best snapshot for matching.
        3. Run the matcher.
        4. Fire the on_event callback.
        """
        direction = self._decide_direction()
        if direction is None:
            # Couldn't determine direction — too ambiguous to act on.
            return

        # ── Identify the product ─────────────────────────────────
        product_name = "unknown"
        score        = 0.0

        if self._snapshots and self.db is not None:
            best_score    = -1.0
            best_snapshot = self._snapshots[0]

            # Run the matcher on every stored snapshot and keep
            # the frame that produced the highest confident score.
            for snap in self._snapshots:
                try:
                    emb    = extract_embedding(snap)
                    result = match(emb, db=self.db)
                    if result["top_score"] > best_score:
                        best_score    = result["top_score"]
                        best_snapshot = snap
                        if result["confident"]:
                            product_name = result["top_name"]
                            score        = result["top_score"]
                except Exception as e:
                    print(f"[zone_tracker] Snapshot match error: {e}")

            # If none of the snapshots was individually "confident",
            # fall back to the best score we saw (mark uncertain).
            if product_name == "unknown" and best_score > 0:
                # Still report something — the caller can show it as uncertain.
                try:
                    emb    = extract_embedding(best_snapshot)
                    result = match(emb, db=self.db)
                    product_name = result["top_name"] + "?"  # "?" signals uncertain
                    score        = result["top_score"]
                except Exception:
                    pass

        elif self._snapshots and self.db is None:
            # No DB loaded — this happens in unit tests or if build_db
            # hasn't been run yet.
            product_name = "no_db"
            score        = 0.0

        # ── Fire callback ─────────────────────────────────────────
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
