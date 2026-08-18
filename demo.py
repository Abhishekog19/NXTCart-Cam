# ---------------------------------------------------------------
# demo.py  —  Main demo script for the instructor review
#
# WHAT IT DOES
# ─────────────
# Opens a live webcam window and continuously:
#   1. Shows the raw camera feed.
#   2. Every time you press SPACE, captures a burst of frames,
#      runs the multi-frame vote, and overlays the result.
#   3. The overlay shows:
#        • Matched product name
#        • Confidence score (%) and margin
#        • Verdict: "✓ CONFIDENT" (green) or "? UNCERTAIN" (red)
#
# In LIVE mode (between scans), the window still shows a real-time
# single-frame prediction so the instructor can see it working
# continuously — the burst vote is the "confirmed" answer.
#
# HOW TO RUN
# ──────────
#   python demo.py
#
# CONTROLS
#   SPACE  →  trigger a full multi-frame scan (5 frames, ~0.7 s)
#   Q      →  quit
# ---------------------------------------------------------------

import time

import cv2
import numpy as np

from ml.config import CAMERA_INDEX
from ml.embedding_extractor import extract_embedding
from ml.matcher import load_database, match
from ml.multi_frame_vote import capture_and_vote

# ── Visual style constants ────────────────────────────────────────
FONT = cv2.FONT_HERSHEY_DUPLEX
FONT_SMALL = cv2.FONT_HERSHEY_SIMPLEX

COLOR_CONFIDENT = (60, 220, 60)      # green
COLOR_UNCERTAIN = (40, 60, 230)      # red-ish (BGR)
COLOR_WHITE     = (255, 255, 255)
COLOR_GRAY      = (160, 160, 160)
COLOR_DARK      = (20, 20, 20)
COLOR_YELLOW    = (0, 215, 255)

OVERLAY_ALPHA = 0.55   # transparency of the info panel background


def draw_overlay(frame: np.ndarray, result: dict, voted: bool = False) -> np.ndarray:
    """
    Draw a semi-transparent info panel on the bottom of the frame.

    Parameters
    ----------
    frame  : BGR image from the webcam.
    result : dict returned by match() or capture_and_vote().
    voted  : True when this is a confirmed multi-frame result.
    """
    h, w = frame.shape[:2]
    out = frame.copy()

    # ── Draw panel background ─────────────────────────────────────
    panel_h = 160
    panel_y = h - panel_h
    overlay = out[panel_y:, :]
    overlay[:] = (overlay * (1 - OVERLAY_ALPHA) + np.array(COLOR_DARK) * OVERLAY_ALPHA).astype(np.uint8)

    # ── Choose colours based on confidence ───────────────────────
    if result.get("confident", False):
        verdict_text  = "CONFIDENT"
        verdict_color = COLOR_CONFIDENT
    else:
        verdict_text  = "UNCERTAIN — needs a clearer look"
        verdict_color = COLOR_UNCERTAIN

    # ── Product name ──────────────────────────────────────────────
    name = result.get("top_name") or result.get("final_name", "—")
    cv2.putText(out, name.replace("_", " ").upper(),
                (16, panel_y + 38), FONT, 1.1, COLOR_WHITE, 2, cv2.LINE_AA)

    # ── Score and margin ──────────────────────────────────────────
    score = result.get("top_score", 0.0)
    if "last_result" in result:          # this came from capture_and_vote
        score = result["last_result"].get("top_score", 0.0)
    margin = result.get("margin", 0.0)
    if "last_result" in result:
        margin = result["last_result"].get("margin", 0.0)

    score_pct = f"Score: {score * 100:.1f}%   Margin: {margin * 100:.1f}%"
    cv2.putText(out, score_pct,
                (16, panel_y + 78), FONT_SMALL, 0.70, COLOR_GRAY, 1, cv2.LINE_AA)

    # ── Verdict ───────────────────────────────────────────────────
    cv2.putText(out, verdict_text,
                (16, panel_y + 118), FONT, 0.85, verdict_color, 2, cv2.LINE_AA)

    # ── Mode indicator ────────────────────────────────────────────
    mode = "[ CONFIRMED SCAN ]" if voted else "[ LIVE PREVIEW ]"
    cv2.putText(out, mode,
                (16, panel_y + 150), FONT_SMALL, 0.55, COLOR_YELLOW, 1, cv2.LINE_AA)

    # ── Corner hint ───────────────────────────────────────────────
    cv2.putText(out, "SPACE=scan  Q=quit",
                (w - 230, 28), FONT_SMALL, 0.6, COLOR_GRAY, 1, cv2.LINE_AA)

    # ── Border around the panel ───────────────────────────────────
    cv2.line(out, (0, panel_y), (w, panel_y), verdict_color, 2)

    return out


def draw_scanning_animation(frame: np.ndarray, progress: float) -> np.ndarray:
    """
    Show a simple scanning animation while the burst vote is running.
    `progress` goes from 0.0 to 1.0.
    """
    h, w = frame.shape[:2]
    out = frame.copy()

    # Horizontal scan bar.
    bar_y = int(h * progress)
    cv2.line(out, (0, bar_y), (w, bar_y), (0, 200, 255), 3)

    # Pulsing text.
    cv2.putText(out, "Scanning…",
                (w // 2 - 80, h // 2), FONT, 1.2, (0, 200, 255), 2, cv2.LINE_AA)
    return out


def main():
    print("[demo] Loading embedding database…")
    db = load_database()

    print(f"[demo] Opening camera {CAMERA_INDEX}…")
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print(
            f"ERROR: Cannot open camera index {CAMERA_INDEX}.\n"
            "Try changing CAMERA_INDEX in ml/config.py."
        )
        return

    # Warm up the model (first call triggers download + load).
    print("[demo] Warming up model (first frame may take a moment)…")
    ok, warmup_frame = cap.read()
    if ok:
        extract_embedding(warmup_frame)
    print("[demo] Ready!  Press SPACE to scan a product, Q to quit.\n")

    window = "NXTCart-Cam  —  Product Recognition"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 800, 600)

    # State for the live single-frame prediction.
    last_live_result: dict = {
        "top_name": "—",
        "top_score": 0.0,
        "margin": 0.0,
        "confident": False,
    }

    # State for the last confirmed (multi-frame) result.
    last_voted_result: dict | None = None
    showing_voted = False
    voted_display_until = 0.0   # timestamp until which we keep showing the voted result

    frame_count = 0
    LIVE_UPDATE_EVERY = 5  # update the live prediction every N frames (keeps it snappy)

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[demo] Warning: dropped frame.")
            continue

        frame_count += 1

        # ── Live single-frame prediction (lightweight, frequent) ──
        if frame_count % LIVE_UPDATE_EVERY == 0:
            try:
                emb = extract_embedding(frame)
                last_live_result = match(emb, db=db)
            except Exception as e:
                print(f"[demo] Live match error: {e}")

        # ── Decide what to display ────────────────────────────────
        now = time.time()
        if showing_voted and now < voted_display_until:
            display_result = last_voted_result
            display_voted = True
        else:
            if showing_voted and now >= voted_display_until:
                showing_voted = False  # expire the confirmed overlay
            display_result = last_live_result
            display_voted = False

        # ── Render the frame ──────────────────────────────────────
        rendered = draw_overlay(frame, display_result, voted=display_voted)
        cv2.imshow(window, rendered)

        # ── Handle keypresses ─────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), ord("Q")):
            print("[demo] Quitting.")
            break

        elif key == ord(" "):
            # ── Full multi-frame scan ─────────────────────────────
            print("[demo] Scanning…")

            # Brief animation while scanning.
            for step in range(10):
                ok2, scan_frame = cap.read()
                if ok2:
                    anim = draw_scanning_animation(scan_frame, step / 10)
                    cv2.imshow(window, anim)
                cv2.waitKey(1)

            voted = capture_and_vote(cap=cap, db=db)

            print(f"[demo] Result: {voted['message']}")
            if "last_result" in voted and voted["last_result"]:
                lr = voted["last_result"]
                print(f"        Score={lr.get('top_score', '?'):.3f}  "
                      f"Margin={lr.get('margin', '?'):.3f}  "
                      f"Confident={voted['confident']}")

            # Package voted result in a compatible dict for draw_overlay.
            last_voted_result = voted
            showing_voted = True
            voted_display_until = time.time() + 5.0  # show for 5 seconds

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
