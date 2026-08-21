# ---------------------------------------------------------------
# live_cart_demo.py  —  Smart Cart Gate Demo
#
# WHAT IT DOES
# ─────────────
# • Streams the webcam feed with the gateway zone drawn over it.
# • Automatically detects items passing through the zone,
#   identifies them, and updates a virtual shopping cart.
# • Nothing needs to be pressed during normal use —
#   just hold the product above the zone and drop/lift it.
#
# LAYOUT
# ───────
# Left panel  (2/3 of window): live camera + zone overlay
# Right panel (1/3 of window): virtual cart list + event log
#
# HOW TO RUN
# ──────────
#   python live_cart_demo.py
#
# CONTROLS
#   R  →  reset cart to empty
#   Q  →  quit
#
# TUNING
# ───────
# All thresholds are in ml/config.py.
# Most importantly:
#   ZONE_RECT        — move/resize the green box to your gateway opening
#   FG_PIXEL_THRESHOLD — raise if flickering lights cause false events
#   EVENT_COOLDOWN_SEC — raise if one slow movement fires twice
# ---------------------------------------------------------------

import time
from collections import deque

import cv2
import numpy as np

from ml.config import CAMERA_INDEX, ZONE_RECT
from ml.matcher import load_database
from ml.zone_tracker import ZoneTracker

# ── UI dimensions ─────────────────────────────────────────────────
CAM_W, CAM_H   = 640, 480    # native capture size
PANEL_W         = 280        # width of the right info panel
WINDOW_W        = CAM_W + PANEL_W
WINDOW_H        = CAM_H

# ── Colours (BGR) ─────────────────────────────────────────────────
C_BG         = (18,  18,  24)   # near-black panel background
C_WHITE      = (255, 255, 255)
C_GRAY       = (140, 140, 150)
C_GREEN      = (60,  210,  80)
C_RED        = (60,   60, 220)
C_YELLOW     = (0,   210, 255)
C_CYAN       = (200, 220,   0)
C_PANEL_LINE = (50,  50,  65)

FONT       = cv2.FONT_HERSHEY_DUPLEX
FONT_SMALL = cv2.FONT_HERSHEY_SIMPLEX

# ── Event log buffer ──────────────────────────────────────────────
MAX_LOG_ENTRIES = 10
_event_log: deque = deque(maxlen=MAX_LOG_ENTRIES)

# ── Virtual cart ──────────────────────────────────────────────────
# A list of dicts, each: {"name": str, "qty": int}
_cart: list[dict] = []


def _add_to_cart(product_name: str) -> None:
    """Increment qty if product already in cart, else append."""
    clean = product_name.rstrip("?")   # strip uncertainty marker
    for entry in _cart:
        if entry["name"] == clean:
            entry["qty"] += 1
            return
    _cart.append({"name": clean, "qty": 1})


def _remove_from_cart(product_name: str) -> None:
    """Decrement qty; remove entry if qty reaches 0."""
    clean = product_name.rstrip("?")
    for entry in _cart:
        if entry["name"] == clean:
            entry["qty"] -= 1
            if entry["qty"] <= 0:
                _cart.remove(entry)
            return
    # Product not found — log but don't crash.
    print(f"[cart] REMOVE requested for '{clean}' but it's not in the cart.")


def on_zone_event(direction: str, product_name: str, score: float) -> None:
    """
    Callback fired by ZoneTracker on each resolved crossing.
    Updates the cart and appends to the event log.
    """
    uncertain = product_name.endswith("?")
    clean = product_name.rstrip("?")

    if direction == "ADD":
        _add_to_cart(product_name)
        action_str = "ADD"
        color = C_GREEN
    else:
        _remove_from_cart(product_name)
        action_str = "REM"
        color = C_RED

    suffix = " [?]" if uncertain else ""
    log_entry = {
        "text":  f"{action_str}: {clean.replace('_', ' ')}{suffix}",
        "color": color,
        "time":  time.strftime("%H:%M:%S"),
    }
    _event_log.appendleft(log_entry)   # newest at top


# ── Panel rendering ───────────────────────────────────────────────

def _draw_panel(panel: np.ndarray, tracker: "ZoneTracker") -> None:
    panel[:] = C_BG
    W = panel.shape[1]
    y = 0

    def hline(yy: int, color: tuple = C_PANEL_LINE) -> int:
        cv2.line(panel, (0, yy), (W, yy), color, 1)
        return yy + 1

    def text(s: str, yy: int, color=C_WHITE, scale=0.55, bold=False) -> int:
        thickness = 2 if bold else 1
        cv2.putText(panel, s, (10, yy), FONT_SMALL, scale, color, thickness, cv2.LINE_AA)
        return yy + int(scale * 38)

    def section(title: str, yy: int) -> int:
        yy = hline(yy, C_PANEL_LINE)
        cv2.rectangle(panel, (0, yy), (W, yy + 22), C_PANEL_LINE, -1)
        cv2.putText(panel, title, (8, yy + 15), FONT_SMALL, 0.48, C_YELLOW, 1, cv2.LINE_AA)
        return yy + 24

    cv2.rectangle(panel, (0, 0), (W, 34), (30, 30, 45), -1)
    cv2.putText(panel, "NXTCart", (8, 24), FONT, 0.75, C_CYAN, 2, cv2.LINE_AA)
    y = 36

    y = section("  ZONE STATUS", y)
    state_color = {"idle": C_GREEN, "tracking": C_YELLOW, "identifying": C_CYAN, "cooldown": C_GRAY}.get(tracker.ui_state, C_WHITE)
    y = text(f"State : {tracker.ui_state.upper()}", y, state_color, 0.50, bold=True)
    y = text(f"Dir   : {tracker.ui_direction}", y, C_WHITE, 0.50)
    y = text(f"FG px : {tracker.ui_fg_pixels}", y, C_GRAY, 0.45)
    y += 4

    y = section("  CART", y)
    if not _cart: y = text("(empty)", y, C_GRAY, 0.50)
    else:
        for entry in _cart:
            line = f"  {entry['name'].replace('_', ' ')}"
            qty_str = f"x{entry['qty']}"
            y = text(line, y, C_WHITE, 0.52)
            (tw, _), _ = cv2.getTextSize(qty_str, FONT_SMALL, 0.52, 1)
            cv2.putText(panel, qty_str, (W - tw - 10, y - 8), FONT_SMALL, 0.52, C_CYAN, 1, cv2.LINE_AA)
    y += 4

    y = section("  EVENTS", y)
    if not _event_log: y = text("(none yet)", y, C_GRAY, 0.45)
    else:
        for entry in list(_event_log)[:7]:
            y = text(f"{entry['time']}  {entry['text']}", y, entry["color"], 0.43)

    controls_y = WINDOW_H - 52
    hline(controls_y)
    cv2.putText(panel, "R = reset cart", (10, controls_y + 16), FONT_SMALL, 0.45, C_GRAY, 1, cv2.LINE_AA)
    cv2.putText(panel, "Q = quit", (10, controls_y + 34), FONT_SMALL, 0.45, C_GRAY, 1, cv2.LINE_AA)

def _draw_cart_hud(cam_view: np.ndarray, tracker: "ZoneTracker") -> None:
    """
    Semi-transparent cart overlay on the camera feed (top-left corner).

    Shows:
      - Header: "CART (N items)"
      - One row per product with quantity right-aligned
      - "(empty)" when cart is empty
      - Animated "| IDENTIFYING..." spinner while background thread runs
      - Coloured border flash for 0.5 s after each ADD (green) / REMOVE (red)
    """
    PAD    = 8
    ROW_H  = 22
    HEADER = 26
    WIDTH  = 210

    n_rows = max(1, len(_cart))
    box_h  = HEADER + n_rows * ROW_H + PAD
    x0, y0 = 8, 8

    # Semi-transparent dark background
    overlay = cam_view.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + WIDTH, y0 + box_h), (10, 10, 20), -1)
    cv2.rectangle(overlay, (x0, y0), (x0 + WIDTH, y0 + box_h), (70, 80, 90), 1)
    cv2.addWeighted(overlay, 0.70, cam_view, 0.30, 0, cam_view)

    # Teal header bar
    total_qty = sum(e["qty"] for e in _cart)
    header_txt = "CART  (%d item%s)" % (total_qty, "s" if total_qty != 1 else "")
    cv2.rectangle(cam_view, (x0, y0), (x0 + WIDTH, y0 + HEADER), (35, 85, 55), -1)
    cv2.putText(cam_view, header_txt, (x0 + PAD, y0 + HEADER - 7),
                FONT_SMALL, 0.46, (200, 255, 210), 1, cv2.LINE_AA)

    # Item rows
    if not _cart:
        cv2.putText(cam_view, "(empty)",
                    (x0 + PAD, y0 + HEADER + ROW_H - 6),
                    FONT_SMALL, 0.42, C_GRAY, 1, cv2.LINE_AA)
    else:
        for i, entry in enumerate(_cart):
            ry   = y0 + HEADER + i * ROW_H
            name = entry["name"].replace("_", " ")
            qty  = "x%d" % entry["qty"]
            # Alternating row tint
            if i % 2 == 0:
                cv2.rectangle(cam_view, (x0 + 1, ry),
                              (x0 + WIDTH - 1, ry + ROW_H), (22, 25, 38), -1)
            cv2.putText(cam_view, "  " + name, (x0 + PAD, ry + ROW_H - 6),
                        FONT_SMALL, 0.42, C_WHITE, 1, cv2.LINE_AA)
            (tw, _), _ = cv2.getTextSize(qty, FONT_SMALL, 0.44, 1)
            cv2.putText(cam_view, qty, (x0 + WIDTH - tw - PAD, ry + ROW_H - 6),
                        FONT_SMALL, 0.44, C_CYAN, 1, cv2.LINE_AA)

    # Identifying spinner (bottom of cam view)
    if tracker.ui_state == "identifying":
        spinner = ["|", "/", "-", "\\"][int(time.time() * 5) % 4]
        cv2.putText(cam_view, "%s  Identifying..." % spinner,
                    (CAM_W // 2 - 90, CAM_H - 12),
                    FONT_SMALL, 0.55, C_YELLOW, 1, cv2.LINE_AA)

    # ADD/REMOVE border flash (0.5 s)
    if tracker.last_event:
        age = time.time() - tracker.last_event["timestamp"]
        if age < 0.5:
            flash_c = C_GREEN if tracker.last_event["direction"] == "ADD" else C_RED
            cv2.rectangle(cam_view, (0, 0), (CAM_W - 1, CAM_H - 1), flash_c, 8)

    # Event banner (bottom strip, fades over 3.5 s)
    if tracker.last_event:
        ev  = tracker.last_event
        age = time.time() - ev["timestamp"]
        if 0 < age < 3.5:
            alpha = max(0.0, 1.0 - age / 3.5)
            bar   = (0, 100, 35) if ev["direction"] == "ADD" else (25, 25, 110)
            strip_y1, strip_y2 = CAM_H - 46, CAM_H
            roi     = cam_view[strip_y1:strip_y2, :]
            bg      = np.full_like(roi, bar)
            cam_view[strip_y1:strip_y2, :] = cv2.addWeighted(
                bg, alpha * 0.80, roi, 1.0 - alpha * 0.80, 0)
            prod = ev["product_name"].replace("_", " ").rstrip("?")
            txt  = "%s: %s  (%d%%)" % (ev["direction"], prod, int(ev["score"] * 100))
            tc   = C_GREEN if ev["direction"] == "ADD" else (110, 110, 255)
            cv2.putText(cam_view, txt, (12, strip_y2 - 12),
                        FONT, 0.72, tc, 2, cv2.LINE_AA)


def main() -> None:
    print("[live_cart_demo] Loading embedding database…")
    try:
        db = load_database()
    except FileNotFoundError as e:
        print(f"WARNING: {e}\nRunning without product identification.")
        db = None

    print(f"[live_cart_demo] Opening camera {CAMERA_INDEX}…")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera {CAMERA_INDEX}.  Change CAMERA_INDEX in ml/config.py.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    tracker = ZoneTracker(on_event=on_zone_event, db=db)

    window = "NXTCart-Cam - Live Cart"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, WINDOW_W, WINDOW_H)

    # Pre-allocate right panel (stays in memory, redrawn each frame).
    panel = np.zeros((WINDOW_H, PANEL_W, 3), dtype=np.uint8)

    print("[live_cart_demo] Ready.  Aim webcam at your gateway opening.")
    print(f"                 Zone rect: {ZONE_RECT}  (edit in ml/config.py)")
    print("                 R = reset cart  |  Q = quit\n")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # ── Zone tracking overlay ─────────────────────────────────
        cam_view = tracker.process(frame)

        # ── Cart HUD (top-left of camera) + event flash ───────────
        _draw_cart_hud(cam_view, tracker)

        # ── Composite: camera + right panel side by side ──────────
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
