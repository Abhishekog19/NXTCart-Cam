# ---------------------------------------------------------------
# capture_dataset.py  --  BUILD A LABELLED BAKE-OFF DATASET
#
# WHY THIS TOOL EXISTS  (read this first)
# ────────────────────────────────────────
# We are about to compare two verifiers (local MobileNet+HSV vs a vision
# model) and declare one more accurate.  That claim is only worth anything if
# both are measured against GROUND TRUTH — and ground truth is something only
# a human standing at the cart can provide.  A verifier cannot label its own
# exam.
#
# So this tool records real transactions and asks YOU what actually happened:
#
#     S  scan the next SKU            (opens a transaction, as in the demo)
#     W  weight change + auto-settle  (the mock scale)
#     G  label the finished transaction GENUINE  — the item really WAS the SKU
#     X  label it SWAP                — you deliberately carried a DIFFERENT item
#     D  discard the finished transaction (fumbled run, mis-scan, etc.)
#     R  reset a stuck transaction
#     Q  quit
#
# WHAT MAKES A GOOD DATASET  (this matters more than the code)
# ─────────────────────────────────────────────────────────────
#   • ~30 GENUINE and ~30 SWAP transactions is enough to see a real
#     difference; fewer and the error rates are noise.
#   • The SWAPS must be the attack we actually care about: a SAME-WEIGHT,
#     DIFFERENT-COLOUR item substituted for the scanned one.  A swap between
#     two obviously different-sized products proves nothing — the weight
#     sensor would already have caught it.
#   • Vary the handling: different angles, speeds, hand positions, and a few
#     deliberately awkward runs.  A dataset of only clean presentations will
#     flatter both backends equally and tell you nothing about the hard cases.
#
# WHY FULL-RESOLUTION CROPS
# ──────────────────────────
# ml/item_follower.py downscales every crop it keeps to IMAGE_SIZE (224) to
# bound RAM on the Pi — correct for the live path, wrong for a dataset.  So
# this tool keeps its OWN buffer of full-resolution crops taken straight from
# the frame via the follower's target bbox.  Downscaling later is trivial;
# upscaling is impossible, and a dataset is captured once but re-scored many
# times (including by models that do not exist yet).
#
# Saved as PNG, not JPEG: JPEG artefacts are a colour-channel confound, and
# the colour channel is exactly what distinguishes a same-weight swap.
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

from ml.config import CAMERA_SOURCE, DATASET_DIR
from ml.custody import CustodyController, TxnState
from ml.detector import BackgroundSubtractorDetector
from ml.events import MockBarcodeSource, MockWeightSource
from ml.frame_source import make_frame_source
from ml.item_follower import FollowStatus, _sample_even
from ml.verifier import ProductVerifier, load_colour_db
from ml.visibility import assess

CAM_W, CAM_H = 640, 480
PANEL_W = 340
FONT = cv2.FONT_HERSHEY_SIMPLEX
WEIGHT_SETTLE_DELAY = 0.6

# How many full-res crops to save per transaction.  More than the live path's
# VERIFY_BURST_FRAMES (12) because disk is cheap and a richer record lets a
# future backend sample differently than today's does.
SAVE_CROPS_PER_TXN = 16

LABEL_GENUINE = "genuine"
LABEL_SWAP = "swap"


class _NullRecognizer:
    """Stand-in so the controller can run without a model present."""
    def embed(self, crop):
        return np.zeros(1, dtype=np.float32)

    def similarity(self, a, b):
        return 0.0


class FullResCollector:
    """
    Collects full-resolution crops of the followed item.

    Runs ALONGSIDE the follower rather than modifying it: the live path's
    downscale-on-capture policy is correct for the Pi and is left alone.  We
    simply take our own crop from the same frame using the follower's
    published target_bbox.

    Deduped by frame seq for the same reason the follower dedupes — one
    physical frame must contribute at most one crop, or a stalled stream
    would pad the dataset with duplicates and make a transaction look
    better-evidenced than it was.
    """

    def __init__(self) -> None:
        self._crops: List[np.ndarray] = []
        self._seen_seq: set = set()

    def observe(self, frame: np.ndarray, bbox, meta) -> None:
        if bbox is None or frame is None:
            return
        seq = getattr(meta, "seq", None)
        if seq is not None:
            if seq in self._seen_seq:
                return
            self._seen_seq.add(seq)

        x, y, w, h = bbox
        fh, fw = frame.shape[:2]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(fw, int(x + w)), min(fh, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        crop = frame[y0:y1, x0:x1].copy()
        # Same usability gate the verifier applies, so the dataset contains
        # the crops a backend would actually have been given — not a
        # more-generous set that would make both look better than they are.
        if not assess(crop).usable:
            return
        self._crops.append(crop)

    @property
    def crops(self) -> List[np.ndarray]:
        return _sample_even(self._crops, SAVE_CROPS_PER_TXN)

    def reset(self) -> None:
        self._crops = []
        self._seen_seq = set()


def _wrap(s: str, width: int) -> List[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:4]


def save_transaction(root: str, sku: str, label: str, txn_id: str,
                     crops: List[np.ndarray], verdict: str,
                     camera: str = "", camera_url: str = "") -> Optional[str]:
    """
    Write one labelled transaction to disk.  Returns its directory, or None
    if there was nothing usable to save.
    """
    if not crops:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_sku = "".join(c if c.isalnum() or c in "-_" else "_" for c in sku)
    name = f"{stamp}_{safe_sku}_{label}"
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)

    for i, c in enumerate(crops):
        cv2.imwrite(os.path.join(path, f"crop_{i:02d}.png"), c)

    meta = {
        "expected_sku": sku,
        "label": label,               # ground truth: genuine | swap
        "txn_id": txn_id,
        "crop_count": len(crops),
        "captured_at": stamp,
        # WHICH CAMERA SHOT THIS.  Recorded because the bake-off compares an
        # ESP32-CAM against a webcam, and two datasets are indistinguishable
        # on disk otherwise — a mislabelled camera would silently invalidate
        # the comparison months later when nobody remembers the session.
        "camera": camera,
        "camera_url": camera_url,
        # The live verdict at capture time, recorded for curiosity only.  The
        # comparison harness RE-RUNS every backend from the images, so this
        # value is never used as a score — it would be circular if it were.
        "live_verdict_at_capture": verdict,
    }
    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return path


def draw_panel(panel, controller, pending, counts, last_saved, hint):
    panel[:] = (14, 14, 20)
    W = panel.shape[1]

    def text(s, yy, color=(255, 255, 255), scale=0.46):
        cv2.putText(panel, s, (10, yy), FONT, scale, color, 1, cv2.LINE_AA)
        return yy + int(scale * 42)

    cv2.rectangle(panel, (0, 0), (W, 32), (24, 24, 38), -1)
    cv2.putText(panel, "Capture Dataset", (8, 22), FONT, 0.62, (215, 235, 0),
                2, cv2.LINE_AA)
    y = 52

    y = text("COLLECTED", y, (0, 210, 255), 0.44)
    y = text(f"  genuine : {counts[LABEL_GENUINE]}", y, (55, 210, 75))
    y = text(f"  swap    : {counts[LABEL_SWAP]}", y, (60, 60, 235))
    y += 6

    y = text("CURRENT", y, (0, 210, 255), 0.44)
    y = text(f"  sku   : {controller.expected_sku or '-'}", y)
    y = text(f"  follow: {controller.follow_status}", y, (200, 200, 200), 0.42)
    y = text(f"  cart  : {'yes' if controller.reached_cart else 'no'}", y,
             (200, 200, 200), 0.42)
    y = text(f"  weight: {'yes' if controller.weight_settled else 'no'}", y,
             (200, 200, 200), 0.42)
    y += 6

    if pending is not None:
        y = text("AWAITING LABEL", y, (0, 170, 255), 0.5)
        y = text(f"  sku  : {pending['sku']}", y, (255, 255, 255), 0.42)
        y = text(f"  crops: {len(pending['crops'])}", y, (255, 255, 255), 0.42)
        y = text("  G=genuine  X=swap  D=discard", y, (0, 170, 255), 0.42)
        y += 4
    elif hint:
        for line in _wrap(hint, 38):
            y = text("  " + line, y, (150, 150, 160), 0.4)

    if last_saved:
        y += 4
        y = text("LAST SAVED", y, (0, 210, 255), 0.42)
        for line in _wrap(last_saved, 38):
            y = text("  " + line, y, (120, 200, 120), 0.36)

    fy = CAM_H - 52
    cv2.line(panel, (0, fy), (W, fy), (40, 40, 55), 1)
    text("S=scan  W=weight  R=reset  Q=quit", fy + 18, (180, 180, 180), 0.42)
    text("swaps: same weight, different colour", fy + 36, (0, 170, 255), 0.36)


def main():
    ap = argparse.ArgumentParser(
        description="Capture a labelled dataset for the verifier bake-off.")
    ap.add_argument("--name", required=True,
                    help="dataset name, e.g. 'kitchen' -> datasets/kitchen/")
    ap.add_argument("--sku", action="append", default=None,
                    help="SKU to cycle with S (repeatable). Defaults to the "
                         "SKUs in the reference database.")
    # ── camera selection ──────────────────────────────────────────
    # The bake-off captures one dataset PER CAMERA (ESP32-CAM vs webcam), so
    # the camera must be selectable here rather than by editing ml/config.py
    # between runs.  A dataset silently captured on the wrong camera looks
    # completely normal on disk and invalidates every number downstream.
    ap.add_argument("--source", default=CAMERA_SOURCE,
                    choices=["webcam", "mjpeg"],
                    help=f"frame source (default: {CAMERA_SOURCE})")
    ap.add_argument("--url", default=None,
                    help="MJPEG stream URL when --source mjpeg "
                         "(default: ESP32_STREAM_URL from config)")
    ap.add_argument("--index", type=int, default=None,
                    help="webcam device index when --source webcam")
    ap.add_argument("--db", default=None,
                    help="reference .pkl for this camera (default: config "
                         "DATABASE_PATH). Only used to discover SKU names and "
                         "to run a live verdict; the bake-off re-scores offline.")
    args = ap.parse_args()

    root = os.path.join(DATASET_DIR, args.name)
    os.makedirs(root, exist_ok=True)
    print(f"[capture] Writing to {root}")

    # Load the recognizer only to discover SKU names and to give the
    # controller a working verifier; accuracy is irrelevant here because we
    # re-score everything offline later.
    appearance_db: Dict[str, list] = {}
    recog = None
    try:
        from ml.matcher import load_database
        from ml.recognizer import EmbeddingRecognizer
        db = load_database(args.db) if args.db else None
        recog = EmbeddingRecognizer(db=db)
        appearance_db = recog.db
    except Exception as e:
        print(f"[capture] No reference database ({e}).")
        print("[capture] That is fine - capture does not need one. Pass "
              "--sku NAME for each product you will scan.")

    skus = list(args.sku) if args.sku else sorted(appearance_db.keys())
    if not skus:
        print("[capture] ERROR: no SKUs. Pass --sku NAME (repeatable).")
        return
    print(f"[capture] SKUs: {skus}")

    barcode = MockBarcodeSource(skus)
    weight = MockWeightSource()
    detector = BackgroundSubtractorDetector()
    verifier = ProductVerifier(recog if recog is not None else _NullRecognizer(),
                               appearance_db=appearance_db,
                               colour_db=load_colour_db(args.db))

    try:
        source = make_frame_source(args.source, width=CAM_W, height=CAM_H,
                                   url=args.url, index=args.index)
    except Exception as e:
        print(f"[capture] ERROR opening camera '{args.source}': {e}")
        return
    print(f"[capture] Camera source: {args.source}"
          + (f"  url={args.url}" if args.url else ""))

    controller = CustodyController(detector, verifier, barcode, weight,
                                   frame_size=(CAM_W, CAM_H))
    collector = FullResCollector()

    window = "NXTCart-Cam - Capture Dataset"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, CAM_W + PANEL_W, CAM_H)
    panel = np.zeros((CAM_H, PANEL_W, 3), dtype=np.uint8)

    counts = {LABEL_GENUINE: 0, LABEL_SWAP: 0}
    # Count what is already on disk so repeated sessions accumulate.
    for d in os.listdir(root):
        if d.endswith(f"_{LABEL_GENUINE}"):
            counts[LABEL_GENUINE] += 1
        elif d.endswith(f"_{LABEL_SWAP}"):
            counts[LABEL_SWAP] += 1

    pending = None          # a finished transaction awaiting your label
    last_saved = ""
    hint = "Press S to scan, carry the item to the cart, then W."
    pending_settle_at = None

    print("[capture] Ready. S=scan  W=weight  G=genuine  X=swap  D=discard  Q=quit")

    while True:
        ok, frame, meta = source.read()
        if not ok or frame is None:
            if not getattr(source, "stopped", True):
                panel[:] = (14, 14, 20)
                cv2.putText(panel, "Waiting for camera...", (12, CAM_H // 2),
                            FONT, 0.5, (0, 170, 255), 1, cv2.LINE_AA)
                blank = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
                cv2.imshow(window, np.hstack([blank, panel]))
                if (cv2.waitKey(30) & 0xFF) in (ord("q"), ord("Q")):
                    break
                continue
            print("[capture] Camera stopped.")
            break
        frame = cv2.resize(frame, (CAM_W, CAM_H))

        if pending_settle_at is not None and time.time() >= pending_settle_at:
            weight.settle(250.0)
            pending_settle_at = None

        # Collect BEFORE process(): process() may finish the transaction and
        # discard the follower, taking target_bbox with it.
        if controller.follower is not None and pending is None:
            collector.observe(frame, controller.follower.target_bbox, meta)

        result = controller.process(frame, meta)

        if result is not None and pending is None:
            crops = collector.crops
            if crops:
                pending = {
                    "sku": result.expected_sku,
                    "txn_id": result.txn_id,
                    "crops": crops,
                    "verdict": result.verdict,
                }
                print(f"[capture] Transaction done ({result.verdict}, "
                      f"{len(crops)} crops). Label it: G=genuine X=swap D=discard")
            else:
                hint = (f"{result.verdict} with no usable crops - nothing to "
                        f"save. Try again.")
                print(f"[capture] {result.verdict}, no usable crops. Skipped.")
                collector.reset()

        # ── draw ──
        cam = frame.copy()
        f = controller.follower
        if f is not None:
            sx, sy, sw, sh = f.scanner_box
            cx, cy, cw, ch = f.cart_box
            cv2.rectangle(cam, (sx, sy), (sx + sw, sy + sh), (90, 90, 110), 1)
            cv2.rectangle(cam, (cx, cy), (cx + cw, cy + ch), (60, 120, 60), 1)
            if f.target_bbox is not None:
                x, y, w, h = f.target_bbox
                cv2.rectangle(cam, (x, y), (x + w, y + h), (215, 235, 0), 2)
        if pending is not None:
            cv2.putText(cam, "LABEL THIS: G / X / D", (12, 28), FONT, 0.7,
                        (0, 170, 255), 2, cv2.LINE_AA)

        draw_panel(panel, controller, pending, counts, last_saved, hint)
        cv2.imshow(window, np.hstack([cam, panel]))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            break

        if pending is not None:
            # While a transaction awaits a label, only label keys act.  This
            # is deliberate: an unlabelled capture is worthless, so it must
            # not be possible to start the next scan and lose it by accident.
            label = None
            if key in (ord("g"), ord("G")):
                label = LABEL_GENUINE
            elif key in (ord("x"), ord("X")):
                label = LABEL_SWAP
            elif key in (ord("d"), ord("D")):
                print("[capture] Discarded.")
                pending = None
                collector.reset()
                hint = "Discarded. Press S to scan again."
                continue
            if label is not None:
                path = save_transaction(root, pending["sku"], label,
                                        pending["txn_id"], pending["crops"],
                                        pending["verdict"],
                                        camera=args.source,
                                        camera_url=args.url or "")
                if path:
                    counts[label] += 1
                    last_saved = os.path.basename(path)
                    print(f"[capture] Saved {label}: {path} "
                          f"({len(pending['crops'])} crops)")
                    hint = "Saved. Press S to scan the next item."
                pending = None
                collector.reset()
            continue

        if key in (ord("s"), ord("S")):
            sku = barcode.scan_next()
            collector.reset()
            hint = f"Scanned '{sku}'. Carry it to the cart, then press W."
            print(f"[capture] Scanned '{sku}'.")
        elif key in (ord("w"), ord("W")):
            weight.begin_change()
            pending_settle_at = time.time() + WEIGHT_SETTLE_DELAY
        elif key in (ord("r"), ord("R")):
            controller.reset()
            collector.reset()
            hint = "Reset. Press S to scan."
            print("[capture] Reset.")

    source.release()
    cv2.destroyAllWindows()
    print(f"\n[capture] Done. genuine={counts[LABEL_GENUINE]} "
          f"swap={counts[LABEL_SWAP]}  ->  {root}")
    total = counts[LABEL_GENUINE] + counts[LABEL_SWAP]
    if total < 20:
        print("[capture] NOTE: fewer than 20 transactions. Error rates from a "
              "dataset this small are mostly noise - aim for ~30 of each.")


if __name__ == "__main__":
    main()
