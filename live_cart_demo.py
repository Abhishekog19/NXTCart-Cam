# ---------------------------------------------------------------
# live_cart_demo.py  --  NXTCart Smart Cart Demo
#
# WHAT THIS DOES
# ───────────────
# Points the webcam at a flat surface (table, mat, tray).
# The entire frame is the "cart surface".
#
# ADD a product
#   Reach in, place the item on the surface, pull your hand away.
#   The system compares the scene before and after — if something
#   appeared → it identifies the item and adds it to the cart.
#
# REMOVE a product
#   Pick up the item and lift/slide it out of frame.
#   The system sees something disappeared from the scene → identifies
#   it from the items already in the cart → removes it.
#
# Multiple items can be added/removed in a single reach-in.
#
# CONTROLS
#   R  →  reset cart to empty
#   Q  →  quit
#
# TUNING (ml/config.py)
#   SCORE_THRESHOLD      — raise if wrong products are matched
#   FG_PIXEL_THRESHOLD   — raise if camera noise triggers false events
#   TEXTURE_STD_THRESHOLD — lower if items have subtle patterns
#   DIFF_THRESHOLD        — raise if lighting flicker causes false diffs
# ---------------------------------------------------------------

import threading
import time
from collections import deque

import cv2
import numpy as np

from ml.config import CAMERA_INDEX
from ml.matcher import load_database
from ml.zone_tracker import ZoneTracker

# ── Window dimensions ─────────────────────────────────────────────
CAM_W, CAM_H = 640, 480
PANEL_W       = 260
WINDOW_W      = CAM_W + PANEL_W
WINDOW_H      = CAM_H

# ── Colours (BGR) ─────────────────────────────────────────────────
C_BG         = (14,  14,  20)
C_WHITE      = (255, 255, 255)
C_GRAY       = (120, 120, 130)
C_GREEN      = (55,  210,  75)
C_RED        = (70,   70, 230)
C_YELLOW     = (0,   210, 255)
C_CYAN       = (215, 235,   0)
C_PANEL_SEP  = (40,  40,  55)

FONT   = cv2.FONT_HERSHEY_DUPLEX
FONT_S = cv2.FONT_HERSHEY_SIMPLEX

# ── Cart & event log ──────────────────────────────────────────────
_cart_lock  = threading.Lock()    # on_zone_event fires from a background thread
_cart: list[dict] = []           # [{"name": str, "qty": int}, ...]
_event_log: deque  = deque(maxlen=12)
_full_db = None                   # full embedding DB (loaded at startup)


# ─────────────────────────────────────────────────────────────────
# CART OPERATIONS  (all called with _cart_lock held)
# ─────────────────────────────────────────────────────────────────

def _add_to_cart(name: str) -> None:
    for e in _cart:
        if e["name"] == name:
            e["qty"] += 1
            return
    _cart.append({"name": name, "qty": 1})


def _remove_from_cart(name: str) -> None:
    for e in _cart:
        if e["name"] == name:
            e["qty"] -= 1
            if e["qty"] <= 0:
                _cart.remove(e)
            return
    print(f"[cart] REMOVE '{name}' — not in cart.")


def _get_cart_db():
    """
    Return a database filtered to only items currently in the cart.
    Called by ZoneTracker during REMOVE scanning so the model only
    has to compare against 1-5 products instead of the full catalogue.
    """
    if _full_db is None:
        return None
    with _cart_lock:
        names = {e["name"] for e in _cart}
    return {k: v for k, v in _full_db.items() if k in names} or None


# ─────────────────────────────────────────────────────────────────
# EVENT CALLBACK  (called from ZoneTracker background thread)
# ─────────────────────────────────────────────────────────────────

def on_zone_event(direction: str, product_name: str, score: float) -> None:
    """Thread-safe callback: update cart + append to event log."""
    clean = product_name.rstrip("?")

    with _cart_lock:
        if direction == "ADD":
            _add_to_cart(clean)
            color  = C_GREEN
            prefix = "ADD"
        else:
            _remove_from_cart(clean)
            color  = C_RED
            prefix = "REM"

    _event_log.appendleft({
        "text":  "%s: %s  (%d%%)" % (prefix, clean.replace("_", " "), int(score * 100)),
        "color": color,
        "time":  time.strftime("%H:%M:%S"),
    })


# ─────────────────────────────────────────────────────────────────
# CAMERA HUD  (drawn directly on cam view each frame)
# ─────────────────────────────────────────────────────────────────

def _draw_cart_hud(cam: np.ndarray, tracker: ZoneTracker) -> None:
    """
    Semi-transparent cart overlay in the top-left of the camera feed.

    Shows the live cart contents so an audience watching the webcam
    can see the cart state without looking at the side panel.

    Also shows:
      • Green/red border flash on ADD/REMOVE (0.5 s)
      • Fading bottom banner with last event (3.5 s)
      • Animated spinner when the model is running
    """
    PAD    = 8
    ROW_H  = 22
    HEADER = 26
    WIDTH  = 215

    with _cart_lock:
        cart_copy   = list(_cart)
        total_qty   = sum(e["qty"] for e in cart_copy)

    n_rows = max(1, len(cart_copy))
    box_h  = HEADER + n_rows * ROW_H + PAD
    x0, y0 = 8, 8

    # Semi-transparent dark background
    ov = cam.copy()
    cv2.rectangle(ov, (x0, y0), (x0 + WIDTH, y0 + box_h), (6, 6, 16), -1)
    cv2.rectangle(ov, (x0, y0), (x0 + WIDTH, y0 + box_h), (55, 65, 75), 1)
    cv2.addWeighted(ov, 0.68, cam, 0.32, 0, cam)

    # Teal header
    header_txt = "CART  (%d item%s)" % (total_qty, "s" if total_qty != 1 else "")
    cv2.rectangle(cam, (x0, y0), (x0 + WIDTH, y0 + HEADER), (28, 75, 48), -1)
    cv2.putText(cam, header_txt, (x0 + PAD, y0 + HEADER - 7),
                FONT_S, 0.46, (185, 255, 205), 1, cv2.LINE_AA)

    # Item rows
    if not cart_copy:
        cv2.putText(cam, "(empty)",
                    (x0 + PAD, y0 + HEADER + ROW_H - 6),
                    FONT_S, 0.42, C_GRAY, 1, cv2.LINE_AA)
    else:
        for i, entry in enumerate(cart_copy):
            ry  = y0 + HEADER + i * ROW_H
            qty = "x%d" % entry["qty"]
            if i % 2 == 0:
                cv2.rectangle(cam, (x0 + 1, ry),
                              (x0 + WIDTH - 1, ry + ROW_H), (18, 20, 32), -1)
            cv2.putText(cam, "  " + entry["name"].replace("_", " "),
                        (x0 + PAD, ry + ROW_H - 6),
                        FONT_S, 0.42, C_WHITE, 1, cv2.LINE_AA)
            (tw, _), _ = cv2.getTextSize(qty, FONT_S, 0.44, 1)
            cv2.putText(cam, qty,
                        (x0 + WIDTH - tw - PAD, ry + ROW_H - 6),
                        FONT_S, 0.44, C_CYAN, 1, cv2.LINE_AA)

    # Spinner while model runs
    if tracker._identifying:
        spin = ["|", "/", "-", "\\"][int(time.time() * 5) % 4]
        cv2.putText(cam, "%s  Analyzing..." % spin,
                    (CAM_W // 2 - 75, CAM_H - 12),
                    FONT_S, 0.52, C_YELLOW, 1, cv2.LINE_AA)

    # Border flash for 0.5 s after each event
    if tracker.last_event:
        age = time.time() - tracker.last_event["timestamp"]
        if age < 0.5:
            fc = C_GREEN if tracker.last_event["direction"] == "ADD" else C_RED
            cv2.rectangle(cam, (0, 0), (CAM_W - 1, CAM_H - 1), fc, 8)

    # Fading bottom banner for 3.5 s
    if tracker.last_event:
        ev  = tracker.last_event
        age = time.time() - ev["timestamp"]
        if 0 < age < 3.5:
            alpha = max(0.0, 1.0 - age / 3.5)
            bar   = (0, 85, 28) if ev["direction"] == "ADD" else (22, 22, 95)
            s1, s2 = CAM_H - 44, CAM_H
            roi = cam[s1:s2, :]
            bg  = np.full_like(roi, bar)
            cam[s1:s2, :] = cv2.addWeighted(
                bg, alpha * 0.82, roi, 1.0 - alpha * 0.82, 0)
            prod = ev["product_name"].replace("_", " ").rstrip("?")
            txt  = "%s: %s  (%d%%)" % (
                ev["direction"], prod, int(ev["score"] * 100))
            tc = C_GREEN if ev["direction"] == "ADD" else (115, 115, 255)
            cv2.putText(cam, txt, (10, s2 - 11),
                        FONT, 0.72, tc, 2, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────
# RIGHT PANEL
# ─────────────────────────────────────────────────────────────────

def _draw_panel(panel: np.ndarray, tracker: ZoneTracker) -> None:
    panel[:] = C_BG
    W = panel.shape[1]
    y = 0

    def hline(yy):
        cv2.line(panel, (0, yy), (W, yy), C_PANEL_SEP, 1)
        return yy + 1

    def text(s, yy, color=C_WHITE, scale=0.50, bold=False):
        cv2.putText(panel, s, (10, yy), FONT_S, scale,
                    color, 2 if bold else 1, cv2.LINE_AA)
        return yy + int(scale * 38)

    def section(title, yy):
        yy = hline(yy)
        cv2.rectangle(panel, (0, yy), (W, yy + 22), C_PANEL_SEP, -1)
        cv2.putText(panel, title, (8, yy + 15),
                    FONT_S, 0.46, C_YELLOW, 1, cv2.LINE_AA)
        return yy + 24

    # Header
    cv2.rectangle(panel, (0, 0), (W, 34), (24, 24, 38), -1)
    cv2.putText(panel, "NXTCart", (8, 24), FONT, 0.72, C_CYAN, 2, cv2.LINE_AA)
    y = 36

    # Tracker status
    y = section("  STATUS", y)
    sc = {
        "learning":  C_GRAY,
        "stable":    C_GREEN,
        "disturbed": C_YELLOW,
        "settling":  (0, 200, 100),
        "cooldown":  C_GRAY,
    }.get(tracker.ui_state, C_WHITE)
    y = text("State: %s" % tracker.ui_state.upper(), y, sc, 0.48, bold=True)
    y = text("FG px: %d" % tracker.ui_fg_pixels,     y, C_GRAY, 0.42)
    y += 4

    # Cart
    y = section("  CART", y)
    with _cart_lock:
        cart_copy = list(_cart)
    if not cart_copy:
        y = text("(empty)", y, C_GRAY, 0.48)
    else:
        for entry in cart_copy:
            name = entry["name"].replace("_", " ")
            qty  = "x%d" % entry["qty"]
            y    = text("  " + name, y, C_WHITE, 0.50)
            (tw, _), _ = cv2.getTextSize(qty, FONT_S, 0.50, 1)
            cv2.putText(panel, qty, (W - tw - 10, y - 8),
                        FONT_S, 0.50, C_CYAN, 1, cv2.LINE_AA)
    y += 4

    # Event log
    y = section("  EVENTS", y)
    if not _event_log:
        y = text("(none yet)", y, C_GRAY, 0.42)
    else:
        for e in list(_event_log)[:8]:
            y = text("%s  %s" % (e["time"], e["text"]), y, e["color"], 0.40)

    # Controls
    ctrl_y = WINDOW_H - 50
    hline(ctrl_y)
    cv2.putText(panel, "R = reset cart",
                (10, ctrl_y + 16), FONT_S, 0.43, C_GRAY, 1, cv2.LINE_AA)
    cv2.putText(panel, "Q = quit",
                (10, ctrl_y + 32), FONT_S, 0.43, C_GRAY, 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    global _full_db

    print("[live_cart_demo] Loading embedding database...")
    try:
        _full_db = load_database()
    except FileNotFoundError as e:
        print("WARNING:", e, "\nRunning without product identification.")

    print("[live_cart_demo] Opening camera %d..." % CAMERA_INDEX)
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("ERROR: Cannot open camera %d." % CAMERA_INDEX)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # eliminate frame queuing lag

    tracker = ZoneTracker(
        on_event    = on_zone_event,
        db          = _full_db,
        get_cart_db = _get_cart_db,
        frame_size  = (CAM_W, CAM_H),
    )

    window = "NXTCart-Cam - Live Cart"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, WINDOW_W, WINDOW_H)

    panel = np.zeros((WINDOW_H, PANEL_W, 3), dtype=np.uint8)

    print("[live_cart_demo] Ready.  (warm-up: ~2 seconds)")
    print("  ADD    — place item in frame, remove hand, hold still.")
    print("  REMOVE — lift item out of frame.")
    print("  R = reset cart  |  Q = quit\n")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        cam_view = tracker.process(frame)
        _draw_cart_hud(cam_view, tracker)
        _draw_panel(panel, tracker)

        composite = np.hstack([cam_view, panel])
        cv2.imshow(window, composite)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            print("[live_cart_demo] Quitting.")
            break
        elif key in (ord("r"), ord("R")):
            with _cart_lock:
                _cart.clear()
            _event_log.clear()
            tracker.last_event = None
            tracker.ui_regions = []
            print("[live_cart_demo] Cart reset.")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
