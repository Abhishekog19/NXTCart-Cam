# ---------------------------------------------------------------
# cart_sim.py  --  TEST THE CAMERA TODAY, WITH A WEBCAM AND REAL PRODUCTS
#
# WHAT THIS IS FOR
# ─────────────────
# The full cart is three sensors plus a ROS 2 brain (see CART_INTEGRATION.md).
# Today only ONE of them exists: the webcam.  This harness runs the REAL camera
# pipeline — follower, verifier, custody, cart ledger — against your webcam and
# real products, with the barcode scanner and load cell replaced by keystrokes.
#
# So what you are testing here is exactly what will run on the cart:
#   • does the camera FOLLOW one item from the scanner side into the cart side,
#   • does it ACCEPT the item you scanned (MATCH),
#   • does it CATCH a same-weight swap (SUSPECT / MISMATCH),
#   • does the cart and the bill go UP on an add and DOWN on a removal.
# Only the scan and the weight are faked, and both are faked at the same seam
# the real drivers plug into (ml/events.py protocols), so no verification logic
# is bypassed.
#
# CONTROLS
#   1..9   "scan" that SKU from the list printed at startup (barcode mock)
#   W      the scale settles with the scanned SKU's expected weight  -> completes an ADD
#   X      the scale DROPS the weight of the last added item         -> triggers a REMOVAL
#   E      the scale drops a weight nothing in the cart matches      -> UNEXPECTED_REMOVAL
#   R      reset the open transaction      B  reset background model
#   Q      quit
#
# THE TEST THAT MATTERS MOST (the attack this module exists to stop)
#   1. Scan product A, carry A across  -> expect MATCH, cart +1
#   2. Scan product A, carry B across  -> expect SUSPECT or MISMATCH, cart unchanged
#      (B should be a DIFFERENT product of similar size/weight — the swap)
# Both must hold on YOUR products in YOUR lighting before the camera is trusted.
#
# HOW TO RUN   (this machine: use `py -3`, not `python`)
#   py -3 cart_sim.py                 # default webcam
#   py -3 cart_sim.py --index 1       # second camera
#   py -3 cart_sim.py --list-cameras  # find the right index
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

from ml.cart import CartFlag, load_prices
from ml.config import CART_CURRENCY, REMOVAL_MIN_DROP_G
from ml.detector import BackgroundSubtractorDetector
from ml.events import MockBarcodeSource, MockWeightSource
from ml.frame_source import make_frame_source
from ml.item_follower import FollowStatus
from ml.lane import LaneController
from ml.verifier import Verdict, load_colour_db

CAM_W, CAM_H = 640, 480
PANEL_W = 360
FONT = cv2.FONT_HERSHEY_SIMPLEX

# A scan is only "complete" once the scale settles, so W is a separate key.
# Default per-SKU weight when weights.json has no entry for a SKU.  The exact
# number does not matter for the camera's verdict (it never sees the weight) —
# it only has to be consistent between the add and the removal.
DEFAULT_WEIGHT_G = 150.0

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

FLAG_COLOR = {
    CartFlag.OK:                 (55, 210, 75),
    CartFlag.SWAP_SUSPECT:       (0, 170, 255),
    CartFlag.MISMATCH:           (60, 60, 235),
    CartFlag.UNAVAILABLE:        (150, 150, 160),
    CartFlag.UNEXPECTED_REMOVAL: (60, 60, 235),
    CartFlag.AMBIGUOUS_REMOVAL:  (0, 170, 255),
    CartFlag.REMOVAL_MISMATCH:   (60, 60, 235),
}


def _load_weights(path: str) -> dict:
    """Optional {sku: grams}; missing/!malformed file just means defaults."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:
        return {}


def _list_cameras(limit: int = 6) -> None:
    print("Probing camera indices (this opens and closes each one)...")
    found = []
    for i in range(limit):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW if os.name == "nt" else 0)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                print(f"  index {i}: OPEN  {w}x{h}")
                found.append(i)
            else:
                print(f"  index {i}: opened but no frame")
        cap.release()
    if not found:
        print("  No cameras found. Check the cable/driver and that no other "
              "app (Zoom/Teams/Camera) holds the device.")
    else:
        print(f"Use:  py -3 cart_sim.py --index {found[0]}")


def _wrap(s, width):
    words = str(s).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def draw_camera(frame, lane):
    out = frame.copy()
    follower = lane.follower
    if follower is not None:
        sx, sy, sw, sh = follower.scanner_box
        cx, cy, cw, ch = follower.cart_box
        cv2.rectangle(out, (sx, sy), (sx + sw, sy + sh), (90, 90, 110), 1)
        cv2.putText(out, "SCANNER side", (sx + 4, sy + 18), FONT, 0.45,
                    (120, 120, 140), 1, cv2.LINE_AA)
        cv2.rectangle(out, (cx, cy), (cx + cw, cy + ch), (60, 120, 60), 1)
        cv2.putText(out, "CART side", (cx + 4, cy + 18), FONT, 0.45,
                    (80, 150, 80), 1, cv2.LINE_AA)
        for i in range(1, len(follower.trail)):
            cv2.line(out, follower.trail[i - 1], follower.trail[i],
                     (215, 235, 0), 2)
        if follower.target_bbox is not None:
            x, y, w, h = follower.target_bbox
            col = STATUS_COLOR.get(lane.follow_status, (255, 255, 255))
            cv2.rectangle(out, (x, y), (x + w, y + h), col, 2)
            cv2.putText(out, "TARGET", (x + 3, max(14, y - 6)), FONT, 0.45,
                        col, 1, cv2.LINE_AA)
    else:
        cv2.putText(out, "Scan a SKU (1..9) to open a transaction",
                    (12, CAM_H - 16), FONT, 0.5, (0, 170, 255), 1, cv2.LINE_AA)
    return out


def draw_panel(panel, lane, state):
    panel[:] = (14, 14, 20)
    W = panel.shape[1]

    def text(s, yy, color=(255, 255, 255), scale=0.44):
        cv2.putText(panel, s, (10, yy), FONT, scale, color, 1, cv2.LINE_AA)
        return yy + int(scale * 40) + 4

    cv2.rectangle(panel, (0, 0), (W, 30), (24, 24, 38), -1)
    cv2.putText(panel, "NXTCart - camera test", (8, 21), FONT, 0.56,
                (215, 235, 0), 2, cv2.LINE_AA)
    y = 48

    if state["no_data"]:
        y = text("NO REFERENCE DB - scans -> UNAVAILABLE", y, (0, 170, 255), 0.4)

    # Live transaction
    y = text("TRANSACTION", y, (0, 210, 255), 0.42)
    y = text("  sku   : %s" % (lane.expected_sku or "-"), y)
    y = text("  follow: %s" % lane.follow_status, y,
             STATUS_COLOR.get(lane.follow_status, (200, 200, 200)), 0.4)
    y = text("  cart side: %s   weight: %s" % (
        "YES" if lane.reached_cart else "no",
        "YES" if lane.weight_settled else "no"), y, (200, 200, 200), 0.4)

    # Last verdict
    v = lane.last_verdict
    y += 2
    y = text("LAST VERDICT", y, (0, 210, 255), 0.42)
    if v is None:
        y = text("  (none yet)", y, (150, 150, 160), 0.4)
    else:
        y = text("  %s" % v.verdict, y,
                 VERDICT_COLOR.get(v.verdict, (255, 255, 255)), 0.56)
        y = text("  appear %.2f  colour %.2f  joint %.0f%%" % (
            v.appearance_score, v.colour_score, v.joint_pass_frac * 100),
            y, (205, 205, 205), 0.38)
        y = text("  crops %d   dw %.0fg" % (v.usable_crops, v.weight_delta),
                 y, (150, 150, 170), 0.38)
        for line in _wrap(v.reason, 44)[:3]:
            y = text("  " + line, y, (165, 165, 175), 0.35)

    # Last cart event
    ev = lane.last_event
    if ev is not None:
        y += 2
        y = text("CART EVENT", y, (0, 210, 255), 0.42)
        y = text("  %s %s" % (ev.kind.upper(), ev.sku or ""), y,
                 FLAG_COLOR.get(ev.flag, (255, 255, 255)), 0.44)
        if ev.flag != CartFlag.OK:
            y = text("  %s" % ev.flag, y, FLAG_COLOR.get(ev.flag), 0.38)
        for line in _wrap(ev.reason, 44)[:2]:
            y = text("  " + line, y, (165, 165, 175), 0.35)

    # The cart + bill
    y += 4
    cv2.line(panel, (0, y - 8), (W, y - 8), (40, 40, 55), 1)
    y = text("CART", y, (0, 210, 255), 0.42)
    lines = lane.ledger.lines()
    if not lines:
        y = text("  (empty)", y, (150, 150, 160), 0.4)
    else:
        for ln in lines[:7]:
            price = ln["line_total"]
            money = ("%s%.2f" % (CART_CURRENCY, price)) if price is not None else "n/a"
            y = text("  %-12s x%d  %s" % (ln["sku"][:12], ln["qty"], money),
                     y, (225, 225, 225), 0.4)
    y = text("  TOTAL  %s%.2f" % (CART_CURRENCY, lane.ledger.subtotal()), y,
             (55, 210, 75), 0.5)
    if lane.ledger.has_unpriced():
        y = text("  (some items unpriced)", y, (120, 120, 140), 0.34)

    # Footer
    fy = CAM_H - 58
    cv2.line(panel, (0, fy), (W, fy), (40, 40, 55), 1)
    text("1-9 scan   W weight   X remove   E bad-remove", fy + 15,
         (180, 180, 180), 0.36)
    text("R reset   B bg-reset   Q quit", fy + 31, (180, 180, 180), 0.36)
    text("%.1f fps   %s" % (state["fps"], state["cam"]), fy + 47,
         (90, 90, 110), 0.36)


def main():
    ap = argparse.ArgumentParser(
        description="Test the NXTCart camera pipeline on a webcam with real "
                    "products; barcode + scale are keystrokes.")
    ap.add_argument("--source", default="webcam", choices=["webcam", "mjpeg"],
                    help="frame source (default webcam)")
    ap.add_argument("--index", type=int, default=None,
                    help="webcam device index (try --list-cameras)")
    ap.add_argument("--url", default=None, help="MJPEG url when --source mjpeg")
    ap.add_argument("--width", type=int, default=CAM_W)
    ap.add_argument("--height", type=int, default=CAM_H)
    ap.add_argument("--weights", default="weights.json",
                    help="optional {sku: grams} map for the fake scale")
    ap.add_argument("--list-cameras", action="store_true",
                    help="probe camera indices and exit")
    args = ap.parse_args()

    if args.list_cameras:
        _list_cameras()
        return 0

    # ── references + model ───────────────────────────────────────
    recog, appearance_db, colour_db = None, {}, {}
    try:
        from ml.recognizer import EmbeddingRecognizer
        recog = EmbeddingRecognizer()
        appearance_db = recog.db or {}
        colour_db = load_colour_db()
    except Exception as e:
        print(f"[cart_sim] No reference database ({e}).")
        print("[cart_sim] Running in NO-DATA mode: every scan -> UNAVAILABLE.")

    skus = sorted(appearance_db.keys())
    no_data = not skus
    if no_data:
        skus = ["unknown_sku"]

    prices = load_prices()
    weights = _load_weights(args.weights)

    print("=" * 62)
    print("  NXTCart - camera test harness (webcam + real products)")
    print("=" * 62)
    print(f"  SKUs in database : {skus}")
    print(f"  colour refs      : {len(colour_db)} SKU(s)")
    print("  scan keys        : " + ", ".join(
        f"{i+1}={s}" for i, s in enumerate(skus[:9])))
    for s in skus[:9]:
        print(f"    {s:<14} price %s%-8s weight %.0f g" % (
            CART_CURRENCY,
            ("%.2f" % prices[s]) if s in prices else "n/a",
            weights.get(s, DEFAULT_WEIGHT_G)))
    print("  Carry ONE item from the SCANNER side to the CART side, then W.")
    print("=" * 62)

    barcode = MockBarcodeSource(skus)
    weight = MockWeightSource()
    detector = BackgroundSubtractorDetector()

    try:
        source = make_frame_source(args.source, width=args.width,
                                   height=args.height, url=args.url,
                                   index=args.index)
    except Exception as e:
        print(f"[cart_sim] ERROR opening camera: {e}")
        print("[cart_sim] Try:  py -3 cart_sim.py --list-cameras")
        return 1

    lane = LaneController(
        recognizer=recog, appearance_db=appearance_db, colour_db=colour_db,
        barcode=barcode, weight=weight, detector=detector, prices=prices,
        frame_size=(args.width, args.height),
        on_event=lambda e: print(f"[cart] {e.kind.upper():6s} "
                                 f"{e.sku or '-':<12s} {e.flag:<18s} {e.reason}"),
    )

    window = "NXTCart - camera test"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, args.width + PANEL_W, args.height)
    panel = np.zeros((args.height, PANEL_W, 3), dtype=np.uint8)

    state = {"no_data": no_data, "fps": 0.0,
             "cam": f"{args.source}:{args.index if args.index is not None else 0}"}
    pending_settle = None          # (grams, txn_id) to settle shortly
    last_added = []                # stack of (sku, grams) for the X key
    scanned_weight = DEFAULT_WEIGHT_G
    fps, last_t = 0.0, time.time()

    while True:
        ok, frame, meta = source.read()
        if not ok or frame is None:
            if not getattr(source, "stopped", True):
                panel[:] = (14, 14, 20)
                cv2.putText(panel, "Waiting for camera...", (12, args.height // 2),
                            FONT, 0.5, (0, 170, 255), 1, cv2.LINE_AA)
                blank = np.zeros((args.height, args.width, 3), dtype=np.uint8)
                cv2.imshow(window, np.hstack([blank, panel]))
                if (cv2.waitKey(30) & 0xFF) in (ord("q"), ord("Q")):
                    break
                continue
            print("[cart_sim] Camera stopped.")
            break
        frame = cv2.resize(frame, (args.width, args.height))

        if pending_settle is not None and time.time() >= pending_settle[0]:
            _, grams, tid = pending_settle
            weight.settle(grams, txn_id=tid)
            pending_settle = None

        events = lane.process(frame, meta)
        for e in events:
            if e.kind == "add":
                last_added.append((e.sku, abs(e.weight_g)))
            elif e.kind == "remove":
                last_added = [p for p in last_added if p[0] != e.sku] or last_added[:-1]

        cam = draw_camera(frame, lane)
        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = 0.85 * fps + 0.15 * (1.0 / dt) if fps else 1.0 / dt
        state["fps"] = fps
        draw_panel(panel, lane, state)
        cv2.imshow(window, np.hstack([cam, panel]))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            break
        elif ord("1") <= key <= ord("9"):
            i = key - ord("1")
            if i < len(skus):
                sku = skus[i]
                scanned_weight = weights.get(sku, DEFAULT_WEIGHT_G)
                tid = barcode.scan(sku)
                print(f"[scan] {sku}  (txn {tid}, expects "
                      f"{scanned_weight:.0f} g) -> carry it across, then W")
        elif key in (ord("w"), ord("W")):
            if lane.expected_sku is None:
                print("[weight] No open scan - press a number key first.")
            else:
                weight.begin_change()
                pending_settle = (time.time() + 0.5, scanned_weight, lane.txn_id)
                print(f"[weight] settling +{scanned_weight:.0f} g ...")
        elif key in (ord("x"), ord("X")):
            if not last_added:
                print("[weight] Cart is empty - nothing to remove.")
            else:
                sku, grams = last_added[-1]
                weight.settle(-grams)
                print(f"[weight] dropping {grams:.0f} g (last added {sku})")
        elif key in (ord("e"), ord("E")):
            bogus = 777.0
            weight.settle(-bogus)
            print(f"[weight] dropping {bogus:.0f} g that matches nothing")
        elif key in (ord("r"), ord("R")):
            lane.reset()
            print("[cart_sim] Transaction reset.")
        elif key in (ord("b"), ord("B")):
            detector.reset()
            print("[cart_sim] Background model reset - hold still a moment.")

    source.release()
    cv2.destroyAllWindows()

    # ── session summary: what you actually proved ────────────────
    print("\n" + "=" * 62)
    print("  SESSION SUMMARY")
    print("=" * 62)
    hist = lane.ledger.history
    adds = [e for e in hist if e.kind == "add"]
    rems = [e for e in hist if e.kind == "remove"]
    flags = [e for e in hist if e.kind == "flag"]
    print(f"  adds: {len(adds)}   removals: {len(rems)}   flags: {len(flags)}")
    for e in flags:
        print(f"    FLAG {e.flag:<20s} {e.sku or '-':<12s} {e.reason}")
    print(f"  final cart : {lane.ledger.quantities()}")
    print(f"  final bill : {CART_CURRENCY}{lane.ledger.subtotal():.2f}")
    print("  Reminder: a MATCH on the item you scanned AND a SUSPECT/MISMATCH")
    print("  on a same-weight swap are the two results that matter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
