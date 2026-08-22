# ---------------------------------------------------------------
# live_cart_demo.py  --  NXTCart live cart, persistent-identity build
#
# WHAT YOU SHOULD SEE (and what to watch for)
# ────────────────────────────────────────────
# Point the webcam at a flat surface.  The whole frame is the cart; the
# thin border band is the EXIT ZONE.
#
#   ADD     place an item on the surface and take your hand away.
#           A yellow "verifying..." box appears, then it locks to a green
#           box with the product name.  That name is now FROZEN.
#
#   COVER   put a second item on top of the first.  THIS IS THE TEST.
#           The covered item's box turns purple (OCCLUDED) but its LABEL
#           DOES NOT CHANGE, and it STAYS IN THE CART.  That is the whole
#           point of the rebuild — watch the label, not the box.
#
#   REMOVE  slide an item out across the frame edge.  Only then does the
#           cart lose it (box goes cyan MOVING -> orange EXITING -> gone).
#
#   HIDE    cover an item completely with your hand and hold.  It goes
#           OCCLUDED then grey LOST — and STILL counts in the cart,
#           because being hidden is not the same as being gone.  Uncover
#           it and it is reacquired by its locked appearance.
#
# CONTROLS
#   R  reset (clears tracks + relearns the background)
#   Q  quit
#
# The cart panel is DERIVED from the tracks every frame — nothing in this
# file ever adds to or removes from a cart list by hand.
# ---------------------------------------------------------------

import time
from collections import deque

import cv2
import numpy as np

from ml.cart_state import cart_lines
from ml.config import CAMERA_INDEX, VISIBILITY_GOOD_RATIO, VISIBILITY_WEAK_RATIO
from ml.detector import BackgroundSubtractorDetector
from ml.identity_tracker import IdentityTracker
from ml.recognizer import EmbeddingRecognizer
from ml.track import TrackState

CAM_W, CAM_H = 640, 480
PANEL_W = 300

FONT = cv2.FONT_HERSHEY_DUPLEX
FONT_S = cv2.FONT_HERSHEY_SIMPLEX

C_BG = (14, 14, 20)
C_WHITE = (255, 255, 255)
C_GRAY = (120, 120, 130)
C_DIM = (70, 70, 82)
C_CYAN = (215, 235, 0)
C_YELLOW = (0, 210, 255)
C_SEP = (40, 40, 55)

# One colour per state so the behaviour is readable at a glance.
STATE_COLOR = {
    TrackState.NEW:       (150, 150, 160),
    TrackState.VERIFYING: (0, 210, 255),    # yellow  – deciding, no identity yet
    TrackState.CONFIRMED: (55, 210, 75),    # green   – just locked
    TrackState.PRESENT:   (55, 210, 75),    # green   – in the cart, visible
    TrackState.MOVING:    (215, 235, 0),    # cyan    – moving
    TrackState.EXITING:   (0, 140, 255),    # orange  – leaving
    TrackState.OCCLUDED:  (220, 90, 220),   # purple  – hidden, STILL counted
    TrackState.LOST:      (130, 130, 130),  # grey    – untracked, STILL counted
    TrackState.REACQUIRE: (255, 170, 0),    # blue    – just found again
}

_transition_log: deque = deque(maxlen=9)


# ─────────────────────────────────────────────────────────────────
# CAMERA VIEW
# ─────────────────────────────────────────────────────────────────

def draw_camera(frame: np.ndarray, tracker: IdentityTracker) -> np.ndarray:
    out = frame.copy()
    zl, zt, zr, zb = tracker.zone

    # Active zone + exit band.
    cv2.rectangle(out, (zl, zt), (zr, zb), (60, 60, 75), 1)
    cv2.putText(out, "cart zone (border = exit)", (zl + 4, zt + 14),
                FONT_S, 0.38, (90, 90, 110), 1, cv2.LINE_AA)

    # Raw detections, drawn faintly — these are candidates, NOT identities.
    for d in tracker.last_detections:
        x, y, w, h = d.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), C_DIM, 1)

    # Tracks.
    for t in tracker.active_tracks():
        x, y, w, h = t.bbox
        color = STATE_COLOR.get(t.state, C_WHITE)
        thick = 3 if t.is_locked else 2
        cv2.rectangle(out, (x, y), (x + w, y + h), color, thick)

        label = t.label()
        state = t.state
        # Lock marker makes "this name can no longer change" explicit.
        head = f"#{t.track_id} {label}" + ("  [LOCKED]" if t.is_locked else "")
        (tw, th), _ = cv2.getTextSize(head, FONT_S, 0.5, 1)
        # Stagger label height per track so that two adjacent/overlapping
        # items (exactly the case we care about) don't hide each other's
        # labels — the label is the thing you are supposed to be watching.
        stagger = 30 * (t.track_id % 2)
        ly = max(th + 4, y - 22 - stagger)
        cv2.rectangle(out, (x, ly - th - 4), (x + max(tw, 96) + 8, ly + 16), (10, 10, 16), -1)
        cv2.rectangle(out, (x, ly - th - 4), (x + max(tw, 96) + 8, ly + 16), color, 1)
        cv2.putText(out, head, (x + 4, ly), FONT_S, 0.5, C_WHITE, 1, cv2.LINE_AA)
        cv2.putText(out, state, (x + 4, ly + 13), FONT_S, 0.44, color, 1, cv2.LINE_AA)

        # Visibility bar — the input to the recognition gate.
        bar_w = max(w, 60)
        vy = y + h + 6
        if vy < CAM_H - 6:
            cv2.rectangle(out, (x, vy), (x + bar_w, vy + 4), (35, 35, 45), -1)
            fill = int(bar_w * float(np.clip(t.visibility_ratio, 0, 1)))
            vis_c = ((55, 210, 75) if t.visibility_ratio >= VISIBILITY_GOOD_RATIO
                     else (0, 210, 255) if t.visibility_ratio >= VISIBILITY_WEAK_RATIO
                     else (70, 70, 230))
            cv2.rectangle(out, (x, vy), (x + fill, vy + 4), vis_c, -1)

    return out


# ─────────────────────────────────────────────────────────────────
# SIDE PANEL
# ─────────────────────────────────────────────────────────────────

def draw_panel(panel: np.ndarray, tracker: IdentityTracker, fps: float) -> None:
    panel[:] = C_BG
    W = panel.shape[1]

    def hline(yy):
        cv2.line(panel, (0, yy), (W, yy), C_SEP, 1)
        return yy + 1

    def text(s, yy, color=C_WHITE, scale=0.46):
        cv2.putText(panel, s, (10, yy), FONT_S, scale, color, 1, cv2.LINE_AA)
        return yy + int(scale * 40)

    def section(title, yy):
        yy = hline(yy)
        cv2.rectangle(panel, (0, yy), (W, yy + 20), C_SEP, -1)
        cv2.putText(panel, title, (8, yy + 14), FONT_S, 0.44, C_YELLOW, 1, cv2.LINE_AA)
        return yy + 23

    cv2.rectangle(panel, (0, 0), (W, 32), (24, 24, 38), -1)
    cv2.putText(panel, "NXTCart", (8, 23), FONT, 0.68, C_CYAN, 2, cv2.LINE_AA)
    cv2.putText(panel, "locked identity", (110, 22), FONT_S, 0.40, C_GRAY, 1, cv2.LINE_AA)
    y = 34

    # ── CART (derived from tracks) ────────────────────────────────
    y = section("  CART  (derived from tracks)", y)
    lines = cart_lines(tracker.tracks)
    if not lines:
        y = text("(empty)", y, C_GRAY)
    else:
        for ln in lines:
            name = ln["name"].replace("_", " ")
            y0 = y
            y = text("  " + name, y, C_WHITE, 0.48)
            qty = "x%d" % ln["qty"]
            (tw, _), _ = cv2.getTextSize(qty, FONT_S, 0.48, 1)
            cv2.putText(panel, qty, (W - tw - 10, y0 + 12), FONT_S, 0.48,
                        C_CYAN, 1, cv2.LINE_AA)
            if ln["note"]:
                y = text("    (%s — still counted)" % ln["note"], y, C_GRAY, 0.38)
    y += 3

    # ── TRACKS ────────────────────────────────────────────────────
    y = section("  TRACKS", y)
    active = tracker.active_tracks()
    if not active:
        y = text("(none)", y, C_GRAY)
    else:
        for t in active[:7]:
            c = STATE_COLOR.get(t.state, C_WHITE)
            y = text("#%d %s" % (t.track_id, t.label()), y, c, 0.44)
            y = text("   %s  vis %d%%" % (t.state, int(t.visibility_ratio * 100)),
                     y, C_GRAY, 0.38)
    y += 3

    # ── TRANSITIONS ───────────────────────────────────────────────
    y = section("  STATE CHANGES", y)
    if not _transition_log:
        y = text("(none yet)", y, C_GRAY, 0.40)
    else:
        for entry in list(_transition_log):
            y = text(entry, y, C_GRAY, 0.36)

    # ── FOOTER ────────────────────────────────────────────────────
    fy = CAM_H - 62
    hline(fy)
    cv2.putText(panel, "purple/grey = hidden but IN cart", (10, fy + 15),
                FONT_S, 0.37, (220, 90, 220), 1, cv2.LINE_AA)
    cv2.putText(panel, "only edge exit removes an item", (10, fy + 29),
                FONT_S, 0.37, (0, 140, 255), 1, cv2.LINE_AA)
    cv2.putText(panel, "R = reset    Q = quit", (10, fy + 45),
                FONT_S, 0.40, C_GRAY, 1, cv2.LINE_AA)
    cv2.putText(panel, "%.1f fps  f%d" % (fps, tracker.frame_idx), (10, fy + 58),
                FONT_S, 0.36, C_DIM, 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("[live_cart_demo] Loading recognizer (embedding DB + model)...")
    try:
        recognizer = EmbeddingRecognizer()
    except FileNotFoundError as e:
        print("ERROR:", e)
        return
    except Exception as e:
        print(f"ERROR: could not initialise the recognizer: {e}")
        return

    print("[live_cart_demo] Opening camera %d..." % CAMERA_INDEX)
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("ERROR: Cannot open camera %d." % CAMERA_INDEX)
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    detector = BackgroundSubtractorDetector()
    tracker = IdentityTracker(detector, recognizer, frame_size=(CAM_W, CAM_H))

    # Warm the model so the first real frame isn't slow.
    ok, warm = cap.read()
    if ok:
        try:
            recognizer.embed(warm)
        except Exception:
            pass

    window = "NXTCart-Cam - Persistent Identity Cart"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, CAM_W + PANEL_W, CAM_H)
    panel = np.zeros((CAM_H, PANEL_W, 3), dtype=np.uint8)

    print("[live_cart_demo] Ready.")
    print("  Place an item, wait for it to lock (green + [LOCKED]).")
    print("  Then cover it with another item: the label must NOT change.")
    print("  Slide an item out of frame to remove it.  R = reset, Q = quit.\n")

    seen_transitions = 0
    fps, last_t = 0.0, time.time()

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        frame = cv2.resize(frame, (CAM_W, CAM_H))
        tracker.process(frame)

        # Mirror any NEW state transitions into the side-panel log.
        for t in tracker.tracks:
            already = _seen.get(t.track_id, 0)
            fresh = t.transitions[already:]
            for (fi, old, new, reason) in fresh:
                _transition_log.appendleft("#%d %s>%s %s" % (
                    t.track_id, old[:4], new[:4], (t.product_id or "")[:9]))
            if fresh:
                _seen[t.track_id] = len(t.transitions)

        cam_view = draw_camera(frame, tracker)
        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = 0.85 * fps + 0.15 * (1.0 / dt) if fps else 1.0 / dt
        draw_panel(panel, tracker, fps)

        cv2.imshow(window, np.hstack([cam_view, panel]))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            break
        if key in (ord("r"), ord("R")):
            tracker.reset()
            _transition_log.clear()
            _seen.clear()
            print("[live_cart_demo] Reset.")

    cap.release()
    cv2.destroyAllWindows()


# Remembers how many transitions per track we have already shown in the
# side panel, so each state change is logged exactly once.
_seen: dict = {}


if __name__ == "__main__":
    main()
