# ---------------------------------------------------------------
# verify_demo.py  --  BARCODE-GATED CAMERA VERIFICATION (laptop demo)
#
# WHAT THIS DEMONSTRATES
# ───────────────────────
# The camera's job in one sentence: given that the barcode says "SKU X",
# confirm that the item which just travelled from the scanner into the cart
# really is X — and catch the swap that weight cannot (a same-weight item of
# a different colour).
#
# Because tonight there is NO hardware, the two non-camera sensors are mock
# drivers you drive from the keyboard.  The CONTROL FLOW is the real thing:
# a scan opens a transaction, the camera follows ONE item to the cart, the
# (mock) scale must change and settle, and only then is a verdict produced.
#
# CONTROLS
#   S   "scan" the next SKU in the database (barcode mock)
#   W   "weight": begin change, then it auto-settles a moment later
#   R   reset the current transaction
#   Q   quit
#
# WHAT YOU SHOULD SEE
#   • With NO database this still runs: scan anything and you get UNAVAILABLE
#     (never a silent accept).  That is the graceful-no-data path.
#   • With a database: scan A, carry A left→right into the cart region, press
#     W → MATCH.  Scan A, carry a DIFFERENT same-size item → SUSPECT/MISMATCH.
#     Cover it with your hand mid-transit → RETRY.  Scan again mid-transit →
#     the open transaction is cancelled (RETRY) and a new one starts.
#
# NOTE ON NUMBERS: the per-verdict latency printed here is a TARGET measured
# on a laptop, not the Raspberry Pi.  Real accuracy and Pi latency are
# tomorrow's validation, on real products and the ESP32-CAM.
# ---------------------------------------------------------------

import time

import cv2
import numpy as np

from ml.config import CAMERA_SOURCE
from ml.custody import CustodyController
from ml.detector import BackgroundSubtractorDetector
from ml.events import MockBarcodeSource, MockWeightSource
from ml.frame_source import make_frame_source
from ml.item_follower import FollowStatus
from ml.verifier import (
    ProductVerifier,
    Verdict,
    load_colour_db,
)

CAM_W, CAM_H = 640, 480
PANEL_W = 320
FONT = cv2.FONT_HERSHEY_SIMPLEX

# Auto-settle delay after W is pressed: begin_change now, settle shortly
# after, so the CHANGING→SETTLED sequence is realistic without a second key.
WEIGHT_SETTLE_DELAY = 0.6

VERDICT_COLOR = {
    Verdict.MATCH:       (55, 210, 75),
    Verdict.SUSPECT:     (0, 170, 255),
    Verdict.MISMATCH:    (60, 60, 235),
    Verdict.RETRY:       (0, 210, 255),
    Verdict.UNAVAILABLE: (150, 150, 160),
}

STATUS_COLOR = {
    FollowStatus.WAITING:      (150, 150, 160),
    FollowStatus.TRACKING:     (215, 235, 0),
    FollowStatus.REACHED_CART: (55, 210, 75),
    FollowStatus.AMBIGUOUS:    (0, 170, 255),
    FollowStatus.MERGED:       (220, 90, 220),
    FollowStatus.LOST:         (130, 130, 130),
}


def _load_recognizer_and_db():
    """
    Try to load the production recognizer + database.  On ANY failure
    (no db, no model), return (None, {}, {}) so the demo still starts and
    shows UNAVAILABLE — the graceful-no-data path.
    """
    try:
        from ml.recognizer import EmbeddingRecognizer
        recog = EmbeddingRecognizer()
        appearance_db = recog.db
        colour_db = load_colour_db()
        skus = sorted(appearance_db.keys())
        print(f"[verify_demo] Loaded {len(skus)} SKU(s): {skus}")
        return recog, appearance_db, colour_db
    except Exception as e:
        print(f"[verify_demo] No reference database ({e}).")
        print("[verify_demo] Running in NO-DATA mode: scans resolve UNAVAILABLE.")
        return None, {}, {}


class _NullRecognizer:
    """Stand-in when no model/db is available; never actually scored."""
    def embed(self, crop):
        return np.zeros(1, dtype=np.float32)

    def similarity(self, a, b):
        return 0.0


def draw_camera(frame, controller, follower):
    out = frame.copy()

    # Scanner region (left) and cart-entry region (right) if a follower exists.
    if follower is not None:
        sx, sy, sw, sh = follower.scanner_box
        cx, cy, cw, ch = follower.cart_box
        cv2.rectangle(out, (sx, sy), (sx + sw, sy + sh), (90, 90, 110), 1)
        cv2.putText(out, "scanner", (sx + 4, sy + 16), FONT, 0.4,
                    (110, 110, 130), 1, cv2.LINE_AA)
        cv2.rectangle(out, (cx, cy), (cx + cw, cy + ch), (60, 120, 60), 1)
        cv2.putText(out, "cart entry", (cx + 4, cy + 16), FONT, 0.4,
                    (80, 150, 80), 1, cv2.LINE_AA)

        # Trajectory trail.
        for i in range(1, len(follower.trail)):
            cv2.line(out, follower.trail[i - 1], follower.trail[i],
                     (215, 235, 0), 1)

        # Locked target box.
        if follower.target_bbox is not None:
            x, y, w, h = follower.target_bbox
            col = STATUS_COLOR.get(controller.follow_status, (255, 255, 255))
            cv2.rectangle(out, (x, y), (x + w, y + h), col, 2)
            cv2.putText(out, "TARGET", (x + 3, max(14, y - 6)), FONT, 0.45,
                        col, 1, cv2.LINE_AA)

    return out


def draw_panel(panel, controller, last_result, fps, no_data, last_latency_ms):
    panel[:] = (14, 14, 20)
    W = panel.shape[1]

    def text(s, yy, color=(255, 255, 255), scale=0.46):
        cv2.putText(panel, s, (10, yy), FONT, scale, color, 1, cv2.LINE_AA)
        return yy + int(scale * 42)

    cv2.rectangle(panel, (0, 0), (W, 32), (24, 24, 38), -1)
    cv2.putText(panel, "NXTCart Verify", (8, 22), FONT, 0.62, (215, 235, 0), 2,
                cv2.LINE_AA)
    y = 52

    if no_data:
        y = text("NO DATABASE", y, (0, 170, 255), 0.5)
        y = text("scans -> UNAVAILABLE", y, (150, 150, 160), 0.4)
        y += 6

    y = text("SCAN (barcode mock)", y, (0, 210, 255), 0.44)
    y = text("  SKU: %s" % (controller.expected_sku or "-"), y, (255, 255, 255))
    y += 4

    y = text("TRANSACTION", y, (0, 210, 255), 0.44)
    y = text("  follow : %s" % controller.follow_status, y,
             STATUS_COLOR.get(controller.follow_status, (200, 200, 200)), 0.42)
    y = text("  reached cart: %s" % ("yes" if controller.reached_cart else "no"),
             y, (200, 200, 200), 0.42)
    y = text("  weight settled: %s" % ("yes" if controller.weight_settled else "no"),
             y, (200, 200, 200), 0.42)
    y += 6

    y = text("LAST VERDICT", y, (0, 210, 255), 0.44)
    if last_result is None:
        y = text("  (none yet)", y, (150, 150, 160))
    else:
        vc = VERDICT_COLOR.get(last_result.verdict, (255, 255, 255))
        y = text("  %s" % last_result.verdict, y, vc, 0.6)
        y = text("  appearance %.2f  (%.0f%% frames)" % (
            last_result.appearance_score,
            last_result.appearance_pass_frac * 100), y, (210, 210, 210), 0.4)
        y = text("  colour     %.2f  (%.0f%% frames)" % (
            last_result.colour_score,
            last_result.colour_pass_frac * 100), y, (210, 210, 210), 0.4)
        y = text("  usable crops: %d" % last_result.usable_crops, y,
                 (210, 210, 210), 0.4)
        # Wrap the reason across lines.
        y += 2
        for line in _wrap(last_result.reason, 40):
            y = text("  " + line, y, (170, 170, 180), 0.38)
        if last_latency_ms is not None:
            y = text("  verify %.0f ms (laptop, target)" % last_latency_ms, y,
                     (120, 120, 140), 0.38)

    # Footer controls.
    fy = CAM_H - 66
    cv2.line(panel, (0, fy), (W, fy), (40, 40, 55), 1)
    text("S=scan  W=weight  R=reset  Q=quit", fy + 16, (180, 180, 180), 0.42)
    text("colour catches same-weight swaps", fy + 34, (0, 170, 255), 0.38)
    text("%.1f fps" % fps, fy + 52, (90, 90, 110), 0.4)


def _wrap(s, width):
    words = s.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:4]


def main():
    print("[verify_demo] Starting camera verification demo...")
    recog, appearance_db, colour_db = _load_recognizer_and_db()
    no_data = recog is None

    skus = sorted(appearance_db.keys())
    barcode = MockBarcodeSource(skus)
    weight = MockWeightSource()
    detector = BackgroundSubtractorDetector()
    verifier = ProductVerifier(
        recog if recog is not None else _NullRecognizer(),
        appearance_db=appearance_db,
        colour_db=colour_db,
    )

    try:
        source = make_frame_source(CAMERA_SOURCE, width=CAM_W, height=CAM_H)
    except Exception as e:
        print(f"[verify_demo] ERROR opening camera: {e}")
        return

    controller = CustodyController(detector, verifier, barcode, weight,
                                   frame_size=(CAM_W, CAM_H))

    window = "NXTCart-Cam - Verify"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, CAM_W + PANEL_W, CAM_H)
    panel = np.zeros((CAM_H, PANEL_W, 3), dtype=np.uint8)

    print("[verify_demo] Ready. S=scan  W=weight  R=reset  Q=quit")

    last_result = None
    last_latency_ms = None
    pending_settle_at = None
    fps, last_t = 0.0, time.time()

    while True:
        ok, frame, meta = source.read()
        if not ok or frame is None:
            print("[verify_demo] Camera stopped.")
            break
        frame = cv2.resize(frame, (CAM_W, CAM_H))

        # Auto-settle the mock scale a moment after W was pressed.
        if pending_settle_at is not None and time.time() >= pending_settle_at:
            weight.settle(250.0)   # arbitrary demo mass
            pending_settle_at = None

        t0 = time.perf_counter()
        result = controller.process(frame, meta)
        if result is not None:
            last_latency_ms = (time.perf_counter() - t0) * 1000.0
            last_result = result
            print(f"[verify_demo] {result.verdict}: {result.reason} "
                  f"(app={result.appearance_score:.2f} "
                  f"col={result.colour_score:.2f} "
                  f"crops={result.usable_crops})")

        cam = draw_camera(frame, controller, controller.follower)
        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = 0.85 * fps + 0.15 * (1.0 / dt) if fps else 1.0 / dt
        draw_panel(panel, controller, last_result, fps, no_data, last_latency_ms)

        cv2.imshow(window, np.hstack([cam, panel]))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            break
        elif key in (ord("s"), ord("S")):
            if no_data:
                # Still exercise the transaction/UNAVAILABLE path with a fake SKU.
                barcode.scan("unknown_sku")
                print("[verify_demo] Scanned 'unknown_sku' (no database).")
            else:
                sku = barcode.scan_next()
                print(f"[verify_demo] Scanned '{sku}'. Carry it to the cart, "
                      f"then press W.")
        elif key in (ord("w"), ord("W")):
            weight.begin_change()
            pending_settle_at = time.time() + WEIGHT_SETTLE_DELAY
            print("[verify_demo] Weight changing... will settle shortly.")
        elif key in (ord("r"), ord("R")):
            # Reset by starting a throwaway scan then clearing — simplest is to
            # rebuild the controller's transaction via a fresh scan of nothing.
            controller.state = controller.state.__class__ if False else "IDLE"
            controller.txn = None
            controller.follower = None
            controller.follow_status = FollowStatus.WAITING
            print("[verify_demo] Transaction reset.")

    source.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
