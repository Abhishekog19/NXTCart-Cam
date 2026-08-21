# ---------------------------------------------------------------
# ml/zone_tracker.py  --  Scene-State Comparison Cart Tracker
#
# CORE IDEA — Why this is better than motion tracking
# ────────────────────────────────────────────────────
# The previous approach tried to infer ADD vs REMOVE from WHICH WAY
# an item moved.  This failed because:
#   • Your hand enters and exits the same frame, confusing the direction.
#   • Repositioning an item looks like a REMOVE then an ADD.
#   • Multiple items create overlapping motion blobs.
#
# This version instead asks: "What changed in the scene?"
#
#   BEFORE snapshot  →  disturbance  →  AFTER snapshot
#
# The difference between BEFORE and AFTER tells us:
#   • Where in the frame something changed  (changed regions)
#   • Whether something APPEARED (ADD) or DISAPPEARED (REMOVE)
#   • Whether an item was merely REPOSITIONED (no cart change)
#   • We can handle multiple changed regions simultaneously.
#
# STATE MACHINE
# ──────────────
#   LEARNING   →  initial background warm-up (don't trigger on startup noise)
#   STABLE     →  scene is still; continuously update BEFORE snapshot
#   DISTURBED  →  motion detected; counting still frames
#   SETTLING   →  motion stopped; collecting still AFTER frames
#   COOLDOWN   →  post-event pause; clearing before next transaction
# ---------------------------------------------------------------

import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np

from ml.config import (
    BEFORE_BUFFER_FRAMES,
    BGS_LEARNING_RATE,
    BGS_METHOD,
    DIFF_THRESHOLD,
    EVENT_COOLDOWN_SEC,
    FG_PIXEL_THRESHOLD,
    LEARNING_FRAMES,
    MIN_CROP_PX,
    MIN_REGION_AREA,
    SCORE_THRESHOLD,
    STABLE_FRAMES_REQUIRED,
    TEXTURE_STD_THRESHOLD,
)
from ml.embedding_extractor import extract_embedding
from ml.matcher import EmbeddingDB, match


class _State:
    LEARNING  = "learning"   # initial warm-up, building background model
    STABLE    = "stable"     # scene still; before-snapshot is accumulating
    DISTURBED = "disturbed"  # motion detected, counting still frames
    SETTLING  = "settling"   # motion stopped; collecting after-frames
    COOLDOWN  = "cooldown"   # post-event pause


class ZoneTracker:
    """
    Full-frame, scene-state-comparison cart tracker.

    Parameters
    ----------
    on_event : callable(direction: str, product_name: str, score: float)
        Called once per confirmed ADD or REMOVE event.

    db : EmbeddingDB, optional
        Full product database — used for ADD scanning.

    get_cart_db : callable() -> EmbeddingDB, optional
        Returns a database containing only items currently in the cart.
        Used for REMOVE scanning (faster, more targeted).

    frame_size : (width, height)
        Camera frame dimensions.
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

        # ── Background subtractor (motion detection only) ─────────
        if BGS_METHOD == "KNN":
            self._bgs = cv2.createBackgroundSubtractorKNN(detectShadows=True)
        else:
            self._bgs = cv2.createBackgroundSubtractorMOG2(detectShadows=True)

        # ── State machine ─────────────────────────────────────────
        self._state         = _State.LEARNING
        self._frame_count   = 0    # counts frames in LEARNING phase
        self._still_count   = 0    # consecutive still frames in DISTURBED

        # ── Frame buffers ─────────────────────────────────────────
        # before_frames: rolling window of recent stable frames.
        #   Updated every frame in STABLE state.
        #   When motion starts, we average these into stable_before.
        self._before_frames: list[np.ndarray] = []

        # after_frames: still frames collected after disturbance settles.
        #   Used to build stable_after for comparison.
        self._after_frames: list[np.ndarray] = []

        # The averaged snapshots used for before/after comparison.
        self._stable_before: Optional[np.ndarray] = None

        # ── Threading ─────────────────────────────────────────────
        self._identifying = False
        self._cart_lock   = threading.Lock()   # protects on_event call order

        # ── Cooldown ──────────────────────────────────────────────
        self._cooldown_until = 0.0

        # ── UI fields ─────────────────────────────────────────────
        self.ui_state     = "learning"
        self.ui_fg_pixels = 0
        self.ui_regions: list[tuple] = []   # (x,y,w,h) of last changed regions
        self.last_event: Optional[dict] = None

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Process one camera frame.  Returns the frame with debug overlays.
        Never blocks — analysis runs in a background thread.
        """
        now = time.time()
        H, W = frame.shape[:2]

        # ── Motion detection ──────────────────────────────────────
        # Apply background subtractor; count definite-foreground pixels.
        fg_mask   = self._bgs.apply(frame, learningRate=BGS_LEARNING_RATE)
        fg_binary = (fg_mask == 255).astype(np.uint8) * 255

        # Small morphological clean-up to remove speckle noise.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_OPEN,  k)
        fg_binary = cv2.morphologyEx(fg_binary, cv2.MORPH_CLOSE, k)

        fg_count           = int(np.sum(fg_binary > 0))
        self.ui_fg_pixels  = fg_count
        motion_active      = fg_count > FG_PIXEL_THRESHOLD

        # ── State machine ─────────────────────────────────────────

        if self._state == _State.LEARNING:
            # Warm-up: let the background model stabilise before we start
            # detecting events.  Accumulate before-frames during this time.
            self._frame_count += 1
            self._accumulate_before(frame)
            if self._frame_count >= LEARNING_FRAMES:
                self._state   = _State.STABLE
                self.ui_state = "stable"

        elif self._state == _State.STABLE:
            # Continuously refresh the before-snapshot.
            self._accumulate_before(frame)

            if motion_active:
                # Scene disturbed.  Freeze the current before-snapshot.
                self._stable_before = self._mean_frame(self._before_frames)
                self._state         = _State.DISTURBED
                self.ui_state       = "disturbed"
                self._still_count   = 0
                self._after_frames.clear()

        elif self._state == _State.DISTURBED:
            # Waiting for motion to stop.
            if motion_active:
                self._still_count = 0
            else:
                self._still_count += 1
                if self._still_count >= STABLE_FRAMES_REQUIRED:
                    # Motion has definitively stopped.
                    self._state       = _State.SETTLING
                    self.ui_state     = "settling"
                    self._still_count = 0
                    self._after_frames.clear()

        elif self._state == _State.SETTLING:
            if motion_active:
                # Motion restarted before we finished — go back to DISTURBED.
                self._state       = _State.DISTURBED
                self.ui_state     = "disturbed"
                self._still_count = 0
                self._after_frames.clear()
            else:
                # Collect still after-frames.
                self._after_frames.append(frame.copy())

                if len(self._after_frames) >= BEFORE_BUFFER_FRAMES:
                    # We have enough after-frames.  Launch analysis.
                    if not self._identifying and self._stable_before is not None:
                        stable_after = self._mean_frame(self._after_frames)
                        self._launch_analysis(self._stable_before, stable_after)

                    # Carry after-frames forward as the new before-baseline.
                    self._before_frames = list(self._after_frames)

                    self._cooldown_until = now + EVENT_COOLDOWN_SEC
                    self._state          = _State.COOLDOWN
                    self.ui_state        = "cooldown"
                    self._after_frames.clear()

        elif self._state == _State.COOLDOWN:
            # Update before-frames so we have a fresh baseline for next cycle.
            self._accumulate_before(frame)

            if now >= self._cooldown_until:
                self._state   = _State.STABLE
                self.ui_state = "stable"
                self.ui_regions = []

        return self._draw(frame, fg_binary)

    # ─────────────────────────────────────────────────────────────
    # FRAME BUFFER HELPERS
    # ─────────────────────────────────────────────────────────────

    def _accumulate_before(self, frame: np.ndarray) -> None:
        """Keep a rolling window of the last BEFORE_BUFFER_FRAMES stable frames."""
        self._before_frames.append(frame.copy())
        if len(self._before_frames) > BEFORE_BUFFER_FRAMES:
            self._before_frames.pop(0)

    @staticmethod
    def _mean_frame(frames: list[np.ndarray]) -> Optional[np.ndarray]:
        """
        Average a list of frames to reduce per-pixel noise.
        Returns None if the list is empty.
        """
        if not frames:
            return None
        return np.mean(
            np.stack(frames, axis=0).astype(np.float32),
            axis=0,
        ).astype(np.uint8)

    # ─────────────────────────────────────────────────────────────
    # ANALYSIS (background thread)
    # ─────────────────────────────────────────────────────────────

    def _launch_analysis(
        self,
        before: np.ndarray,
        after:  np.ndarray,
    ) -> None:
        """Launch the before/after scene comparison in a daemon thread."""
        self._identifying = True
        threading.Thread(
            target=self._analyze_threaded,
            args=(before, after),
            daemon=True,
        ).start()

    def _analyze_threaded(
        self,
        before: np.ndarray,
        after:  np.ndarray,
    ) -> None:
        """
        Compare BEFORE and AFTER snapshots and fire cart events.

        Steps:
          1. Compute pixel difference image.
          2. Threshold → binary changed mask.
          3. Morphological clean-up → solid blobs.
          4. Find contours → candidate changed regions.
          5. For each large enough region:
               a. Crop BEFORE and AFTER to the region's bounding box.
               b. Compute texture (grayscale std dev) of each crop.
               c. Classify: ADD / REMOVE / REPOSITION.
               d. Scan the appropriate crop.  Fire event if confident.
        """
        try:
            W, H = self.frame_w, self.frame_h

            # ── Step 1-3: compute and clean the change mask ───────
            diff      = cv2.absdiff(before, after)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

            _, thresh = cv2.threshold(
                diff_gray, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY
            )

            # Large close kernel fills gaps inside a product blob.
            k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
            thresh   = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, k_close)
            # Open kernel removes remaining small noise after closing.
            k_open   = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (12, 12))
            thresh   = cv2.morphologyEx(thresh, cv2.MORPH_OPEN,  k_open)

            # ── Step 4: find contours ─────────────────────────────
            contours, _ = cv2.findContours(
                thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            regions = []
            for cnt in contours:
                if cv2.contourArea(cnt) >= MIN_REGION_AREA:
                    regions.append(cv2.boundingRect(cnt))

            self.ui_regions = regions

            if not regions:
                print("[zone_tracker] No significant changed regions found.")
                return

            print(f"[zone_tracker] {len(regions)} changed region(s) — scanning...")

            # ── Step 5: classify and scan each region ─────────────
            for (rx, ry, rw, rh) in regions:
                self._process_region(before, after, rx, ry, rw, rh, W, H)

        except Exception as e:
            print(f"[zone_tracker] Analysis error: {e}")
        finally:
            self._identifying = False

    def _process_region(
        self,
        before: np.ndarray,
        after:  np.ndarray,
        rx: int, ry: int, rw: int, rh: int,
        W: int,  H:  int,
    ) -> None:
        """
        Classify one changed region as ADD, REMOVE, or REPOSITION,
        then scan and fire the appropriate event(s).
        """
        # Pad the bounding box so the item's full body is captured.
        pad = 25
        x1 = max(0, rx - pad);   y1 = max(0, ry - pad)
        x2 = min(W, rx + rw + pad); y2 = min(H, ry + rh + pad)

        if (x2 - x1) < MIN_CROP_PX or (y2 - y1) < MIN_CROP_PX:
            return  # crop is too small to identify

        crop_b = before[y1:y2, x1:x2]  # what was there BEFORE
        crop_a = after [y1:y2, x1:x2]  # what is  there AFTER

        # ── Texture check ─────────────────────────────────────────
        # Items have labels, colour blocks, text → high std dev.
        # An empty surface (desk, mat) is uniform → low std dev.
        std_b = float(np.std(
            cv2.cvtColor(crop_b, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ))
        std_a = float(np.std(
            cv2.cvtColor(crop_a, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ))

        has_b = std_b > TEXTURE_STD_THRESHOLD
        has_a = std_a > TEXTURE_STD_THRESHOLD

        print(
            f"[zone_tracker]  region ({x1},{y1})-({x2},{y2})  "
            f"std_before={std_b:.1f}  std_after={std_a:.1f}  "
            f"has_before={has_b}  has_after={has_a}"
        )

        if has_a and not has_b:
            # Something appeared → ADD (scan the after crop).
            self._scan_and_fire("ADD", crop_a)

        elif has_b and not has_a:
            # Something disappeared → REMOVE (scan the before crop).
            self._scan_and_fire("REMOVE", crop_b)

        elif has_b and has_a:
            # Content exists in both frames — item may have been
            # repositioned, or a completely different item placed.
            # Identify both crops.  If the same product → reposition (no event).
            # If different products → REMOVE old, ADD new.
            name_b, score_b = self._identify(crop_b, use_cart_db=True)
            name_a, score_a = self._identify(crop_a, use_cart_db=False)

            if (
                name_b is not None
                and name_b == name_a
                and score_b >= SCORE_THRESHOLD
                and score_a >= SCORE_THRESHOLD
            ):
                print(
                    f"[zone_tracker]  REPOSITIONED '{name_b}' "
                    f"(score_b={score_b:.3f}, score_a={score_a:.3f}) — no cart change."
                )
            else:
                # Different items (or one is unidentifiable) → treat as swap.
                if name_b is not None and score_b >= SCORE_THRESHOLD:
                    self._fire_event("REMOVE", name_b, score_b)
                if name_a is not None and score_a >= SCORE_THRESHOLD:
                    self._fire_event("ADD", name_a, score_a)

        else:
            # Neither crop has clear item content — probably just lighting
            # change or noise.  Ignore.
            print("[zone_tracker]  Region has no item content in either frame — skipping.")

    # ─────────────────────────────────────────────────────────────
    # MATCHING HELPERS
    # ─────────────────────────────────────────────────────────────

    def _get_db_for_direction(self, direction: str) -> Optional[EmbeddingDB]:
        """
        Return the correct database for scanning:
          ADD    → full product database
          REMOVE → cart-only database (faster, avoids hallucinating items
                   that aren't in the cart)
        """
        if direction == "REMOVE" and self.get_cart_db is not None:
            cart_db = self.get_cart_db()
            if not cart_db:
                print("[zone_tracker] REMOVE: cart is empty, ignoring.")
                return None
            return cart_db
        return self.db

    def _identify(
        self,
        crop: np.ndarray,
        use_cart_db: bool = False,
    ) -> tuple[Optional[str], float]:
        """
        Run embedding + match on a crop.

        Returns (product_name, score) or (None, 0.0) on failure.
        """
        try:
            db = self.get_cart_db() if (use_cart_db and self.get_cart_db) else self.db
            if not db:
                return None, 0.0
            emb    = extract_embedding(crop)
            result = match(emb, db=db)
            return result["top_name"], result["top_score"]
        except Exception as e:
            print(f"[zone_tracker] Identify error: {e}")
            return None, 0.0

    def _scan_and_fire(self, direction: str, crop: np.ndarray) -> None:
        """Identify a crop and fire event if score passes threshold."""
        db = self._get_db_for_direction(direction)
        if db is None:
            return

        try:
            emb    = extract_embedding(crop)
            result = match(emb, db=db)
            score  = result["top_score"]
            name   = result["top_name"]

            if score < SCORE_THRESHOLD:
                print(
                    f"[zone_tracker] {direction} below threshold "
                    f"(score={score:.3f} < {SCORE_THRESHOLD}) — ignored."
                )
                return

            self._fire_event(direction, name, score)

        except Exception as e:
            print(f"[zone_tracker] Scan error ({direction}): {e}")

    def _fire_event(self, direction: str, name: str, score: float) -> None:
        """Record and broadcast a confirmed ADD/REMOVE event."""
        event = {
            "direction":    direction,
            "product_name": name,
            "score":        round(score, 4),
            "timestamp":    time.time(),
        }
        with self._cart_lock:
            self.last_event = event

        print(
            f"[zone_tracker] EVENT: {direction}  "
            f"product={name}  score={score:.3f}"
        )
        self.on_event(direction, name, score)

    # ─────────────────────────────────────────────────────────────
    # DRAWING
    # ─────────────────────────────────────────────────────────────

    def _draw(
        self,
        frame: np.ndarray,
        fg_binary: np.ndarray,
    ) -> np.ndarray:
        """
        Draw a lightweight debug overlay:
          • State label (top-left)
          • Changed-region bounding boxes (yellow) from last analysis
          • FG pixel count (bottom-left)
          • Tiny FG mask inset (top-right)
          • "Analyzing..." spinner when background thread runs
        """
        out = frame.copy()
        W, H = self.frame_w, self.frame_h

        state_color = {
            _State.LEARNING:  (120, 120, 130),
            _State.STABLE:    (0,   200,   0),
            _State.DISTURBED: (0,   190, 255),
            _State.SETTLING:  (0,   200, 120),
            _State.COOLDOWN:  (100, 100, 120),
        }.get(self._state, (255, 255, 255))

        # ── State label ───────────────────────────────────────────
        cv2.putText(out, self.ui_state.upper(),
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.68,
                    state_color, 2, cv2.LINE_AA)

        # ── FG pixel count ────────────────────────────────────────
        cv2.putText(out, "fg: %d" % self.ui_fg_pixels,
                    (10, H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.40,
                    (100, 100, 115), 1, cv2.LINE_AA)

        # ── Changed regions from last analysis ────────────────────
        for (rx, ry, rw, rh) in self.ui_regions:
            cv2.rectangle(out, (rx, ry), (rx + rw, ry + rh), (0, 220, 255), 2)
            cv2.putText(out, "changed", (rx + 4, ry - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 220, 255), 1, cv2.LINE_AA)

        # ── Analyzing spinner ─────────────────────────────────────
        if self._identifying:
            spin = ["|", "/", "-", "\\"][int(time.time() * 5) % 4]
            cv2.putText(out, "%s  Analyzing scene..." % spin,
                        (W // 2 - 90, H - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 200, 255), 1, cv2.LINE_AA)

        # ── Tiny FG mask inset (top-right) ─────────────────────────
        try:
            iw, ih = W // 5, H // 5
            ins = cv2.resize(fg_binary, (iw, ih))
            ins = cv2.cvtColor(ins, cv2.COLOR_GRAY2BGR)
            out[4 : 4 + ih, W - iw - 4 : W - 4] = ins
        except Exception:
            pass

        return out
