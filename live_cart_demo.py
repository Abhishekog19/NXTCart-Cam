# ---------------------------------------------------------------
# live_cart_demo.py  --  NXTCart Smart Cart Demo
#
# HOW IT WORKS
# ─────────────
# Point the webcam at a flat surface (table, mat, floor of a box).
# The entire camera frame is the "cart surface".
#
#   ADD a product:
#     Bring the item into the camera frame from any edge.
#     Place it down and hold still for ~1 second.
#     The system scans the still item and adds it to the cart.
#
#   REMOVE a product:
#     Pick up the item and slide/lift it out of the camera frame.
#     The system scans the item as it exits and removes it from the cart.
#     Only compares against items already in the cart — fast and accurate.
#
# CONTROLS
#   R  →  reset cart
#   Q  →  quit
#
# TUNING (ml/config.py)
#   FG_PIXEL_THRESHOLD  — raise if camera noise causes false triggers
#   EDGE_MARGIN_FRACTION — how close to the edge counts as "exiting"
#   SETTLE_WAIT_SEC     — how long to hold still before ADD scans
# ---------------------------------------------------------------

import time
from collections import deque

import cv2
import numpy as np

from ml.config import CAMERA_INDEX
from ml.matcher import load_database
from ml.zone_tracker import ZoneTracker

# ── UI dimensions ─────────────────────────────────────────────────
CAM_W, CAM_H = 640, 480
PANEL_W       = 260
WINDOW_W      = CAM_W + PANEL_W
WINDOW_H      = CAM_H

# ── Colours (BGR) ─────────────────────────────────────────────────
C_BG         = (15,  15,  22)
C_WHITE      = (255, 255, 255)
C_GRAY       = (130, 130, 140)
C_GREEN      = (60,  210,  80)
C_RED        = (70,   70, 230)
C_YELLOW     = (0,   210, 255)
C_CYAN       = (210, 230,   0)
C_PANEL_LINE = (45,  45,  60)

FONT       = cv2.FONT_HERSHEY_DUPLEX
FONT_S     = cv2.FONT_HERSHEY_SIMPLEX

# ── Global state ──────────────────────────────────────────────────
MAX_LOG = 10
_event_log: deque = deque(maxlen=MAX_LOG)
_cart: list[dict] = []          # [{"name": str, "qty": int}, ...]
_full_db = None                  # full embedding DB (loaded once at startup)


# ─────────────────────────────────────────────────────────────────
# CART OPERATIONS
# ─────────────────────────────────────────────────────────────────

def _add_to_cart(name: str) -> None:
    for entry in _cart:
        if entry["name"] == name:
            entry["qty"] += 1
            return
    _cart.append({"name": name, "qty": 1})


def _remove_from_cart(name: str) -> None:
    for entry in _cart:
        if entry["name"] == name:
            entry["qty"] -= 1
            if entry["qty"] <= 0:
                _cart.remove(entry)
            return
    print(f"[cart] REMOVE '{name}' — not in cart (ignored).")


def _get_cart_db():
    """
    Build and return a database containing ONLY the items currently in
    the cart.

    This is passed to ZoneTracker so that REMOVE events only search
    through products that are actually in the cart — faster and smarter
    than searching the whole product catalogue.
    """
    if _full_db is None or not _cart:
        return None
    return {
        e["name"]: _full_db[e["name"]]
        for e in _cart
        if e["name"] in _full_db
    }


# ─────────────────────────────────────────────────────────────────
# EVENT CALLBACK (fired by ZoneTracker background thread)
# ─────────────────────────────────────────────────────────────────

def on_zone_event(direction: str, product_name: str, score: float) -> None:
    """Called once per confirmed ADD or REMOVE crossing."""
    clean = product_name.rstrip("?")

    if direction == "ADD":
        _add_to_cart(clean)
        log_color  = C_GREEN
        log_prefix = "ADD"
    else:
        _remove_from_cart(clean)
        log_color  = C_RED
        log_prefix = "REM"

    _event_log.appendleft({
        "text":  "%s: %s  (%d%%)" % (log_prefix, clean.replace("_", " "), int(score * 100)),
        "color": log_color,
        "time":  time.strftime("%H:%M:%S"),
    })


# ─────────────────────────────────────────────────────────────────
# CAMERA FEED HUD — cart overlay drawn directly on the cam frame
# ─────────────────────────────────────────────────────────────────

def _draw_cart_hud(cam_view: np.ndarray, tracker: ZoneTracker) -> None:
    """
    Semi-transparent cart status box in the top-left corner of the
    camera feed, plus:
      - Coloured border flash on ADD (green) / REMOVE (red)
      - Fading bottom banner showing the last event
      - Animated spinner when the model is running
    """
    PAD    = 8
    ROW_H  = 22
    HEADER = 26
    WIDTH  = 215

    n_rows = max(1, len(_cart))
    box_h  = HEADER + n_rows * ROW_H + PAD
    x0, y0 = 8, 8

    # Semi-transparent dark background
    overlay = cam_view.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + WIDTH, y0 + box_h), (8, 8, 18), -1)
    cv2.rectangle(overlay, (x0, y0), (x0 + WIDTH, y0 + box_h), (60, 70, 80), 1)
    cv2.addWeighted(overlay, 0.68, cam_view, 0.32, 0, cam_view)

    # Teal header bar
    total_qty  = sum(e["qty"] for e in _cart)
    header_txt = "CART  (%d item%s)" % (total_qty, "s" if total_qty != 1 else "")
    cv2.rectangle(cam_view, (x0, y0), (x0 + WIDTH, y0 + HEADER), (30, 80, 50), -1)
    cv2.putText(cam_view, header_txt, (x0 + PAD, y0 + HEADER - 7),
                FONT_S, 0.46, (190, 255, 210), 1, cv2.LINE_AA)

    # Item rows
    if not _cart:
        cv2.putText(cam_view, "(empty)",
                    (x0 + PAD, y0 + HEADER + ROW_H - 6),
                    FONT_S, 0.42, C_GRAY, 1, cv2.LINE_AA)
    else:
        for i, entry in enumerate(_cart):
            ry   = y0 + HEADER + i * ROW_H
            name = entry["name"].replace("_", " ")
            qty  = "x%d" % entry["qty"]
            if i % 2 == 0:
                cv2.rectangle(cam_view, (x0 + 1, ry),
                              (x0 + WIDTH - 1, ry + ROW_H), (20, 22, 35), -1)
            cv2.putText(cam_view, "  " + name, (x0 + PAD, ry + ROW_H - 6),
                        FONT_S, 0.42, C_WHITE, 1, cv2.LINE_AA)
            (tw, _), _ = cv2.getTextSize(qty, FONT_S, 0.44, 1)
            cv2.putText(cam_view, qty,
                        (x0 + WIDTH - tw - PAD, ry + ROW_H - 6),
                        FONT_S, 0.44, C_CYAN, 1, cv2.LINE_AA)

    # Animated spinner while the model is running
    if tracker.ui_state == "identifying":
        spin = ["|", "/", "-", "\\"][int(time.time() * 5) % 4]
        cv2.putText(cam_view, "%s  Identifying..." % spin,
                    (CAM_W // 2 - 85, CAM_H - 12),
                    FONT_S, 0.55, C_YELLOW, 1, cv2.LINE_AA)

    # Border flash: 0.5 s green (ADD) or red (REMOVE) border
    if tracker.last_event:
        age = time.time() - tracker.last_event["timestamp"]
        if age < 0.5:
            fc = C_GREEN if tracker.last_event["direction"] == "ADD" else C_RED
            cv2.rectangle(cam_view, (0, 0), (CAM_W - 1, CAM_H - 1), fc, 8)

    # Bottom banner fading over 3.5 s
    if tracker.last_event:
        ev  = tracker.last_event
        age = time.time() - ev["timestamp"]
        if 0 < age < 3.5:
            alpha = max(0.0, 1.0 - age / 3.5)
            bar   = (0, 90, 30) if ev["direction"] == "ADD" else (25, 25, 100)
            s1, s2 = CAM_H - 44, CAM_H
            roi = cam_view[s1:s2, :]
            bg  = np.full_like(roi, bar)
            cam_view[s1:s2, :] = cv2.addWeighted(
                bg, alpha * 0.82, roi, 1.0 - alpha * 0.82, 0)
            prod = ev["product_name"].replace("_", " ").rstrip("?")
            txt  = "%s: %s  (%d%%)" % (
                ev["direction"], prod, int(ev["score"] * 100))
            tc = C_GREEN if ev["direction"] == "ADD" else (110, 110, 255)
            cv2.putText(cam_view, txt, (10, s2 - 11),
                        FONT, 0.72, tc, 2, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────
# RIGHT PANEL
# ─────────────────────────────────────────────────────────────────

def _draw_panel(panel: np.ndarray, tracker: ZoneTracker) -> None:
    panel[:] = C_BG
    W = panel.shape[1]
    y = 0

    def hline(yy):
        cv2.line(panel, (0, yy), (W, yy), C_PANEL_LINE, 1)
        return yy + 1

    def text(s, yy, color=C_WHITE, scale=0.52, bold=False):
        cv2.putText(panel, s, (10, yy), FONT_S, scale,
                    color, 2 if bold else 1, cv2.LINE_AA)
        return yy + int(scale * 38)

    def section(title, yy):
        yy = hline(yy)
        cv2.rectangle(panel, (0, yy), (W, yy + 22), C_PANEL_LINE, -1)
        cv2.putText(panel, title, (8, yy + 15),
                    FONT_S, 0.46, C_YELLOW, 1, cv2.LINE_AA)
        return yy + 24

    # Header
    cv2.rectangle(panel, (0, 0), (W, 34), (28, 28, 42), -1)
    cv2.putText(panel, "NXTCart", (8, 24), FONT, 0.72, C_CYAN, 2, cv2.LINE_AA)
    y = 36

    # Tracker status
    y = section("  STATUS", y)
    sc = {"idle": C_GREEN, "tracking": C_YELLOW,
          "settling": (0, 200, 100), "identifying": C_CYAN,
          "cooldown": C_GRAY}.get(tracker.ui_state, C_WHITE)
    y = text("State: %s" % tracker.ui_state.upper(), y, sc, 0.48, bold=True)
    y = text("Motion: %s" % tracker.ui_direction, y, C_WHITE, 0.46)
    y = text("FG px: %d" % tracker.ui_fg_pixels, y, C_GRAY, 0.42)
    y += 4

    # Cart
    y = section("  CART", y)
    if not _cart:
        y = text("(empty)", y, C_GRAY, 0.48)
    else:
        for entry in _cart:
            name  = entry["name"].replace("_", " ")
            qty   = "x%d" % entry["qty"]
            y = text("  " + name, y, C_WHITE, 0.50)
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

    # Controls (bottom)
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
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # no frame queuing = no lag

    tracker = ZoneTracker(
        on_event    = on_zone_event,
        db          = _full_db,
        get_cart_db = _get_cart_db,       # cart-only DB for fast REMOVE matching
        frame_size  = (CAM_W, CAM_H),
    )

    window = "NXTCart-Cam - Live Cart"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, WINDOW_W, WINDOW_H)

    panel = np.zeros((WINDOW_H, PANEL_W, 3), dtype=np.uint8)

    print("[live_cart_demo] Ready.")
    print("  ADD:    bring item into frame, place it down, hold still.")
    print("  REMOVE: pick item up and slide it out of frame.")
    print("  R = reset cart  |  Q = quit\n")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        cam_view = tracker.process(frame)

        # Cart HUD + flash overlaid directly on cam view
        _draw_cart_hud(cam_view, tracker)

        # Assemble final composite
        _draw_panel(panel, tracker)
        composite = np.hstack([cam_view, panel])

        cv2.imshow(window, composite)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            print("[live_cart_demo] Quitting.")
            break
        elif key in (ord("r"), ord("R")):
            _cart.clear()
            _event_log.clear()
            tracker.last_event = None
            print("[live_cart_demo] Cart reset.")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
