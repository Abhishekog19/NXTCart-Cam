#!/usr/bin/env python3
# ---------------------------------------------------------------
# test_scripted.py  --  SCRIPTED ACCURACY HARNESS
#
# WHAT THIS IS FOR
# ─────────────────
# Runs a FIXED SEQUENCE of actions against the real pipeline and logs, for
# each step, what the cart actually did versus what it was supposed to do.
#
#   add chawal                 -> expect  chawal:1
#   add shampoo over chawal    -> expect  chawal:1, shampoo:1     <- THE TEST
#   remove shampoo             -> expect  chawal:1
#   remove chawal              -> expect  (empty)
#
# THE METRIC THAT MATTERS
# ────────────────────────
#   Correct ADDs          the item appeared in the cart
#   Correct REMOVEs       the item left the cart
#   FALSE cart changes    the cart changed to something WRONG   <- must be 0
#   Uncertain/no-action   the cart declined to change
#
# "Uncertain" is deliberately counted SEPARATELY from a false change, and it
# is NOT a failure of the safety property: doing nothing is always preferable
# to corrupting the cart. The run only FAILS on a false cart change.
#
# THREE MODES
# ────────────
#   --mode synthetic   (default)  real detector (MOG2 + watershed) + real
#                                 matcher, driven by rendered frames.
#                                 No camera, no TFLite. Deterministic.
#                                 Tests: detection -> tracking -> cart.
#
#   --mode oracle                 perfect detector (exact visible region of
#                                 each object) + real matcher.
#                                 Isolates the identity / state-machine /
#                                 cart logic from detector noise, so you can
#                                 tell WHICH layer a failure came from.
#
#   --mode live                    your webcam + the real MobileNet
#                                 recognizer. YOU perform each action and
#                                 press SPACE. This is the real accuracy
#                                 number for your hardware and lighting.
#
# USAGE
#   python test_scripted.py
#   python test_scripted.py --mode oracle
#   python test_scripted.py --script scripts/hide_and_reveal.txt
#   python test_scripted.py --mode live --script scripts/basic_overlap.txt
#   python test_scripted.py --save-frames runs/     (annotated PNG per step)
#
# SCRIPT FILE FORMAT (see scripts/*.txt)
#   action label   |  expected cart      |  scene after the action
#   add chawal     |  chawal:1           |  chawal@150,150,150,150
#   ...
# The third column is geometry for the synthetic/oracle modes and is ignored
# in live mode. Draw order is left-to-right, so the LAST object listed is on
# TOP (that is how you express "shampoo covering chawal").
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ml.config import CAMERA_INDEX
from ml.detector import BackgroundSubtractorDetector, Detection, OracleDetector
from ml.identity_tracker import IdentityTracker
from ml.recognizer import ColorCodeRecognizer

FRAME_W, FRAME_H = 640, 480

# ── synthetic timing ─────────────────────────────────────────────
WARMUP_FRAMES = 60   # empty-scene frames so MOG2 learns the background
SETTLE_FRAMES = 34   # frames held after each action (verification needs time)
SLIDE_FRAMES  = 16   # frames used to slide an item out of / across the frame
SLIDE_STEP    = 30   # px per frame while sliding (>> MOVING_MIN_DISPLACEMENT)

# ── product colours for the synthetic/oracle recognizer ──────────
# Distinct, strongly saturated hues. The background is pure grey
# (saturation 0), which ColorCodeRecognizer ignores by design.
PRODUCT_COLORS: Dict[str, Tuple[int, int, int]] = {
    "chawal":  (235,  60,  35),   # blue
    "shampoo": ( 40,  45, 230),   # red
    "soap":    ( 55, 200,  60),   # green
    "jaljira": ( 40, 205, 235),   # yellow
    "gel":     (215,  55, 205),   # magenta
}

# A stand-in for "a hand covering everything" — grey, so the recognizer
# finds nothing recognisable in it, exactly like a real hand would be a
# non-product blob.
OCCLUDER_NAME = "hand"
OCCLUDER_COLOR = (210, 214, 218)   # light grey: visible to MOG2, invisible
                                   # to the colour recognizer (saturation ~9)


# ═════════════════════════════════════════════════════════════════
# SCRIPT MODEL
# ═════════════════════════════════════════════════════════════════

@dataclass
class Obj:
    """One object in a scene. Draw order = z-order (later is on top)."""
    name: str
    bbox: Tuple[int, int, int, int]


@dataclass
class Step:
    label: str
    expect: Dict[str, int]
    scene: List[Obj] = field(default_factory=list)


DEFAULT_SCRIPT = """
# action label              | expected cart        | scene after the action
add chawal                  | chawal:1             | chawal@130,150,160,170
add shampoo covering chawal | chawal:1, shampoo:1  | chawal@130,150,160,170 shampoo@175,120,150,215
remove shampoo              | chawal:1             | chawal@130,150,160,170
remove chawal               | -                    |
"""


def parse_expect(text: str) -> Dict[str, int]:
    """'chawal:1, shampoo:2' -> {'chawal': 1, 'shampoo': 2}.  '-' -> {}."""
    text = text.strip()
    if not text or text in {"-", "empty", "(empty)", "none"}:
        return {}
    out: Dict[str, int] = {}
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, qty = part.split(":", 1)
        elif " x" in part:
            name, qty = part.rsplit(" x", 1)
        else:
            name, qty = part, "1"
        out[name.strip()] = int(qty.strip().lstrip("x") or 1)
    return out


def parse_scene(text: str) -> List[Obj]:
    """'chawal@130,150,160,170 shampoo@175,120,150,215' -> [Obj, Obj]."""
    objs: List[Obj] = []
    for tok in text.split():
        if "@" not in tok:
            raise ValueError(f"scene item '{tok}' must look like name@x,y,w,h")
        name, geom = tok.split("@", 1)
        nums = [int(v) for v in geom.split(",")]
        if len(nums) != 4:
            raise ValueError(f"scene item '{tok}' needs exactly x,y,w,h")
        objs.append(Obj(name.strip(), (nums[0], nums[1], nums[2], nums[3])))
    return objs


def parse_script(text: str) -> List[Step]:
    steps: List[Step] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split("|")]
        while len(cols) < 3:
            cols.append("")
        steps.append(Step(cols[0], parse_expect(cols[1]), parse_scene(cols[2])))
    return steps


def load_script(path: Optional[str]) -> List[Step]:
    if not path:
        return parse_script(DEFAULT_SCRIPT)
    with open(path, "r", encoding="utf-8") as f:
        return parse_script(f.read())


# ═════════════════════════════════════════════════════════════════
# SYNTHETIC SCENE RENDERING
# ═════════════════════════════════════════════════════════════════

def make_background(seed: int = 7) -> np.ndarray:
    """A textured but colourless (grey) surface — MOG2 sees texture, the
    colour recognizer sees nothing worth matching."""
    rng = np.random.default_rng(seed)
    grey = rng.integers(88, 152, size=(FRAME_H, FRAME_W, 1), dtype=np.uint8)
    bg = np.repeat(grey, 3, axis=2)
    return cv2.GaussianBlur(bg, (5, 5), 0)


def _color_for(name: str) -> Tuple[int, int, int]:
    if name == OCCLUDER_NAME:
        return OCCLUDER_COLOR
    if name not in PRODUCT_COLORS:
        raise KeyError(
            f"'{name}' has no synthetic colour. Known: "
            f"{sorted(PRODUCT_COLORS)} + '{OCCLUDER_NAME}'"
        )
    return PRODUCT_COLORS[name]


def render_scene(objs: List[Obj], bg: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Draw the scene in z-order and return (bgr_frame, id_mask).

    id_mask[y, x] == i+1 means "object i is the VISIBLE one at this pixel",
    which is exactly the ground truth a perfect detector would report.
    """
    frame = bg.copy()
    idm = np.zeros((FRAME_H, FRAME_W), dtype=np.uint8)

    for i, o in enumerate(objs, start=1):
        x, y, w, h = o.bbox
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(FRAME_W, x + w), min(FRAME_H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue                      # entirely off-frame
        col = _color_for(o.name)
        edge = tuple(int(c * 0.62) for c in col)   # darker, same hue
        cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), col, -1)
        cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), edge, 3)
        cv2.rectangle(idm, (x0, y0), (x1 - 1, y1 - 1), i, -1)

    return frame, idm


def oracle_detections(idm: np.ndarray, n_objs: int, min_area: int = 900) -> List[Detection]:
    """
    Turn the ground-truth id mask into detections — the largest visible
    component of each object. This is what a PERFECT detector would emit,
    including correctly shrunken boxes for partly covered objects.

    Note it carries NO identity: just bbox + quality, same as any other
    Detector. Recognition still has to read real pixels from the frame.
    """
    dets: List[Detection] = []
    for i in range(1, n_objs + 1):
        m = (idm == i).astype(np.uint8)
        if int(m.sum()) == 0:
            continue                       # fully covered -> no detection
        n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n_lab <= 1:
            continue
        # biggest visible piece (ignore label 0 = background)
        best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h, area = (int(stats[best, cv2.CC_STAT_LEFT]),
                            int(stats[best, cv2.CC_STAT_TOP]),
                            int(stats[best, cv2.CC_STAT_WIDTH]),
                            int(stats[best, cv2.CC_STAT_HEIGHT]),
                            int(stats[best, cv2.CC_STAT_AREA]))
        if area < min_area:
            continue
        quality = float(area) / float(max(w * h, 1))
        dets.append(Detection(bbox=(x, y, w, h),
                              mask=(labels == best).astype(np.uint8) * 255,
                              quality=quality))
    return dets


# ═════════════════════════════════════════════════════════════════
# SCENE ANIMATION  (turns "remove shampoo" into real outward motion)
# ═════════════════════════════════════════════════════════════════

def _exit_vector(bbox: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """Unit-ish direction toward the NEAREST frame edge."""
    x, y, w, h = bbox
    cx, cy = x + w / 2.0, y + h / 2.0
    d = {"l": cx, "r": FRAME_W - cx, "t": cy, "b": FRAME_H - cy}
    nearest = min(d, key=d.get)
    return {"l": (-1, 0), "r": (1, 0), "t": (0, -1), "b": (0, 1)}[nearest]


def _lerp_box(a, b, t: float) -> Tuple[int, int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))  # type: ignore


def _off_frame(bbox: Tuple[int, int, int, int]) -> bool:
    x, y, w, h = bbox
    return x + w <= 0 or y + h <= 0 or x >= FRAME_W or y >= FRAME_H


def animate(prev: List[Obj], new: List[Obj]) -> List[List[Obj]]:
    """
    Build the frame-by-frame scenes that get us from `prev` to `new`.

    • An object that DISAPPEARS is slid out across the nearest frame edge.
      This matters: the state machine refuses to remove an item that merely
      vanishes, so a test that teleported items away would never produce a
      REMOVE at all. The harness has to physically carry it out.
    • An object that APPEARS is placed directly at its final position (an
      item being set down).
    • An object that MOVES is interpolated.

    Objects are identified by name, so a script should not list the same
    product twice in one scene.
    """
    prev_by = {o.name: o.bbox for o in prev}
    new_by = {o.name: o.bbox for o in new}
    leaving = [n for n in prev_by if n not in new_by]
    moving = [n for n in new_by if n in prev_by and new_by[n] != prev_by[n]]

    scenes: List[List[Obj]] = []

    if leaving or moving:
        for f in range(1, SLIDE_FRAMES + 1):
            t = f / float(SLIDE_FRAMES)
            scene: List[Obj] = []
            # everything that stays keeps the script's z-order (bottom)
            for o in new:
                if o.name in prev_by and o.name in moving:
                    scene.append(Obj(o.name, _lerp_box(prev_by[o.name], o.bbox, t)))
                elif o.name in prev_by:
                    scene.append(Obj(o.name, o.bbox))
            # departing items ride on top — you slide the top item out
            for n in leaving:
                dx, dy = _exit_vector(prev_by[n])
                x, y, w, h = prev_by[n]
                box = (x + dx * SLIDE_STEP * f, y + dy * SLIDE_STEP * f, w, h)
                if not _off_frame(box):
                    scene.append(Obj(n, box))
            scenes.append(scene)

    # arrivals appear in place, in the script's z-order
    scenes.append(list(new))
    return scenes


# ═════════════════════════════════════════════════════════════════
# SCORING
# ═════════════════════════════════════════════════════════════════

CORRECT = "CORRECT"
NO_ACTION = "UNCERTAIN"
FALSE_CHANGE = "FALSE-CHANGE"


@dataclass
class StepResult:
    label: str
    intent: str                  # ADD / REMOVE / MIXED / HOLD
    expect: Dict[str, int]
    before: Dict[str, int]
    actual: Dict[str, int]
    outcome: str
    note: str = ""


def infer_intent(before: Dict[str, int], expect: Dict[str, int]) -> str:
    added = any(expect.get(k, 0) > before.get(k, 0) for k in set(before) | set(expect))
    removed = any(expect.get(k, 0) < before.get(k, 0) for k in set(before) | set(expect))
    if added and removed:
        return "MIXED"
    if added:
        return "ADD"
    if removed:
        return "REMOVE"
    return "HOLD"


def cart_str(c: Dict[str, int]) -> str:
    if not c:
        return "(empty)"
    return ", ".join(f"{k}:{v}" for k, v in sorted(c.items()))


def score_step(step: Step, before: Dict[str, int], actual: Dict[str, int]) -> StepResult:
    intent = infer_intent(before, step.expect)

    if actual == step.expect:
        outcome, note = CORRECT, ""
    elif actual == before:
        outcome = NO_ACTION
        note = "cart unchanged — declined to act (safe)"
    else:
        outcome = FALSE_CHANGE
        keys = set(before) | set(actual) | set(step.expect)
        bits = []
        for k in sorted(keys):
            a, e = actual.get(k, 0), step.expect.get(k, 0)
            if a != e:
                bits.append(f"{k}: got {a}, expected {e}")
        note = "; ".join(bits)

    return StepResult(step.label, intent, dict(step.expect),
                      dict(before), dict(actual), outcome, note)


def report(results: List[StepResult], mode: str) -> int:
    """Print the per-step log and the metrics. Returns a process exit code."""
    W = 78
    print()
    print("═" * W)
    print(f"  SCRIPTED RUN RESULTS   (mode: {mode})")
    print("═" * W)

    for i, r in enumerate(results, start=1):
        flag = {CORRECT: "OK  ", NO_ACTION: "?   ", FALSE_CHANGE: "FAIL"}[r.outcome]
        print(f"\n [{flag}] step {i}: {r.label}   ({r.intent})")
        print(f"        before   : {cart_str(r.before)}")
        print(f"        expected : {cart_str(r.expect)}")
        print(f"        actual   : {cart_str(r.actual)}")
        if r.note:
            print(f"        note     : {r.note}")

    adds = [r for r in results if r.intent == "ADD"]
    rems = [r for r in results if r.intent == "REMOVE"]
    correct_adds = sum(1 for r in adds if r.outcome == CORRECT)
    correct_rems = sum(1 for r in rems if r.outcome == CORRECT)
    false_changes = [r for r in results if r.outcome == FALSE_CHANGE]
    uncertain = [r for r in results if r.outcome == NO_ACTION]
    other = [r for r in results if r.intent in ("MIXED", "HOLD")]

    print()
    print("─" * W)
    print("  METRICS")
    print("─" * W)
    print(f"  Correct ADDs             : {correct_adds} / {len(adds)}")
    print(f"  Correct REMOVEs          : {correct_rems} / {len(rems)}")
    print(f"  FALSE cart changes       : {len(false_changes)}"
          f"   <-- must be 0")
    print(f"  Uncertain / no action    : {len(uncertain)}"
          f"   (safe: no action beats a wrong action)")
    if other:
        correct_other = sum(1 for r in other if r.outcome == CORRECT)
        print(f"  Other steps (hold/mixed) : {correct_other} / {len(other)} correct")
    print(f"  Steps total              : {len(results)}")
    print("─" * W)

    if false_changes:
        print("  RESULT: FAIL — the cart was changed to something wrong.")
        for r in false_changes:
            print(f"          • {r.label}: {r.note}")
        code = 1
    elif uncertain:
        print("  RESULT: PASS (safety) with misses — nothing wrong entered the")
        print("          cart, but these steps did not complete:")
        for r in uncertain:
            print(f"          • {r.label}")
        code = 0
    else:
        print("  RESULT: PASS — every step did exactly what it should.")
        code = 0
    print("═" * W)
    return code


# ═════════════════════════════════════════════════════════════════
# HEADLESS RUNNER  (synthetic + oracle)
# ═════════════════════════════════════════════════════════════════

def run_headless(steps: List[Step], mode: str,
                 save_dir: Optional[str] = None,
                 quiet: bool = False) -> List[StepResult]:
    for s in steps:
        for o in s.scene:
            _color_for(o.name)          # fail fast on unknown product names

    bg = make_background()
    recognizer = ColorCodeRecognizer(PRODUCT_COLORS)
    detector = OracleDetector() if mode == "oracle" else BackgroundSubtractorDetector()
    tracker = IdentityTracker(detector, recognizer, frame_size=(FRAME_W, FRAME_H))

    last_frame = {"f": bg}

    def push(objs: List[Obj]) -> None:
        frame, idm = render_scene(objs, bg)
        if mode == "oracle":
            detector.set(oracle_detections(idm, len(objs)))   # type: ignore[attr-defined]
        tracker.process(frame)
        last_frame["f"] = frame

    if not quiet:
        print(f"[test_scripted] warming background ({WARMUP_FRAMES} empty frames)...")
    for _ in range(WARMUP_FRAMES):
        push([])

    results: List[StepResult] = []
    prev_scene: List[Obj] = []
    before = tracker.cart()

    for i, step in enumerate(steps, start=1):
        if not quiet:
            print(f"\n[test_scripted] ── step {i}: {step.label} "
                  f"(expect {cart_str(step.expect)}) ──")
        for scene in animate(prev_scene, step.scene):
            push(scene)
        for _ in range(SETTLE_FRAMES):
            push(step.scene)

        actual = tracker.cart()
        results.append(score_step(step, before, actual))
        if save_dir:
            save_annotated(save_dir, i, step, last_frame["f"], tracker)
        before = actual
        prev_scene = step.scene

    return results


def save_annotated(save_dir: str, idx: int, step: Step,
                   frame: np.ndarray, tracker: IdentityTracker) -> None:
    """Write the end-of-step frame with the live UI overlay, as evidence."""
    from live_cart_demo import PANEL_W, draw_camera, draw_panel
    os.makedirs(save_dir, exist_ok=True)
    cam = draw_camera(frame, tracker)
    panel = np.zeros((frame.shape[0], PANEL_W, 3), dtype=np.uint8)
    draw_panel(panel, tracker, 0.0)
    safe = "".join(c if c.isalnum() else "_" for c in step.label)[:40]
    path = os.path.join(save_dir, f"step{idx:02d}_{safe}.png")
    cv2.imwrite(path, np.hstack([cam, panel]))
    print(f"[test_scripted] wrote {path}")


# ═════════════════════════════════════════════════════════════════
# LIVE RUNNER  (webcam + the real MobileNet recognizer)
# ═════════════════════════════════════════════════════════════════

def run_live(steps: List[Step], save_dir: Optional[str] = None) -> List[StepResult]:
    """
    You perform each action in front of the camera, then press SPACE to
    record the outcome of that step. ESC/Q aborts. The window is the same
    UI as live_cart_demo, so you can watch the states while you test.
    """
    from live_cart_demo import PANEL_W, draw_camera, draw_panel
    from ml.recognizer import EmbeddingRecognizer

    print("[test_scripted] loading recognizer (embedding DB + model)...")
    recognizer = EmbeddingRecognizer()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera {CAMERA_INDEX}.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    detector = BackgroundSubtractorDetector()
    tracker = IdentityTracker(detector, recognizer, frame_size=(FRAME_W, FRAME_H))

    window = "NXTCart scripted test  --  SPACE = step done, Q = abort"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, FRAME_W + PANEL_W, FRAME_H)
    panel = np.zeros((FRAME_H, PANEL_W, 3), dtype=np.uint8)

    print("\nKeep the surface empty for a few seconds so the background is learned.")
    print("For each step: perform the action, wait for the labels to settle,")
    print("then press SPACE. Press Q to abort the run.\n")

    results: List[StepResult] = []
    before = tracker.cart()
    aborted = False

    for i, step in enumerate(steps, start=1):
        print(f"[step {i}/{len(steps)}]  ACTION: {step.label}"
              f"   (expect {cart_str(step.expect)})")
        banner = f"STEP {i}/{len(steps)}: {step.label}"
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
            tracker.process(frame)

            cam = draw_camera(frame, tracker)
            cv2.rectangle(cam, (0, 0), (FRAME_W, 26), (20, 20, 30), -1)
            cv2.putText(cam, banner, (8, 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.52, (0, 210, 255), 1, cv2.LINE_AA)
            draw_panel(panel, tracker, 0.0)
            cv2.imshow(window, np.hstack([cam, panel]))

            key = cv2.waitKey(1) & 0xFF
            if key == 32:                       # SPACE
                break
            if key in (ord("q"), ord("Q"), 27):  # Q / ESC
                aborted = True
                break
        if aborted:
            print("[test_scripted] aborted by user.")
            break

        actual = tracker.cart()
        r = score_step(step, before, actual)
        results.append(r)
        print(f"           -> actual {cart_str(actual)}   [{r.outcome}]\n")
        if save_dir:
            save_annotated(save_dir, i, step, frame, tracker)
        before = actual

    cap.release()
    cv2.destroyAllWindows()
    return results


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run a scripted action sequence against the persistent-"
                    "identity cart and report accuracy metrics.")
    ap.add_argument("--mode", choices=["synthetic", "oracle", "live"],
                    default="synthetic",
                    help="synthetic = rendered frames + real detector (default); "
                         "oracle = perfect detector (isolates tracking logic); "
                         "live = webcam + real model")
    ap.add_argument("--script", default=None,
                    help="path to a script file (default: built-in overlap script)")
    ap.add_argument("--save-frames", default=None, metavar="DIR",
                    help="write an annotated PNG at the end of each step")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-frame/step chatter (metrics still printed)")
    args = ap.parse_args()

    steps = load_script(args.script)
    if not steps:
        print("No steps found in the script.")
        return 2

    print(f"[test_scripted] {len(steps)} steps, mode = {args.mode}")
    if args.mode == "live":
        results = run_live(steps, args.save_frames)
    else:
        results = run_headless(steps, args.mode, args.save_frames, args.quiet)

    if not results:
        print("No steps were recorded.")
        return 2
    return report(results, args.mode)


if __name__ == "__main__":
    sys.exit(main())
