# ---------------------------------------------------------------
# ml/config.py  --  ALL tuneable parameters live here.
#
# After you capture your reference photos and run the system for
# the first time, tweak these numbers so the demo behaves well
# with your specific products.
# ---------------------------------------------------------------

import os

# ── Webcam ──────────────────────────────────────────────────────
# 0 = built-in webcam, 1 = first external webcam, etc.
CAMERA_INDEX = 0

# ── Paths ────────────────────────────────────────────────────────
REFERENCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")
DATABASE_PATH  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embedding_db.pkl")
MODEL_PATH     = os.path.join(os.path.dirname(__file__), "mobilenet_v2_quant.tflite")

# ── Model input ──────────────────────────────────────────────────
IMAGE_SIZE = 224

# ── Matching thresholds ──────────────────────────────────────────
# SCORE_THRESHOLD:
#   Minimum cosine similarity for a match to count.
#   Your products scored 0.70-0.78 in earlier tests, so 0.55 gives headroom.
SCORE_THRESHOLD = 0.55

# MARGIN_THRESHOLD:
#   Minimum gap between the #1 and #2 product scores.
#   Prevents guessing when two products look similar.
MARGIN_THRESHOLD = 0.03

# ── Background subtractor ─────────────────────────────────────────
# MOG2 is faster; KNN handles more lighting variation.
BGS_METHOD = "MOG2"

# How quickly the background model absorbs static objects.
# Lower = faster absorption (settled item disappears from foreground sooner).
BGS_LEARNING_RATE = 0.005

# ── Motion detection ─────────────────────────────────────────────
# Minimum foreground pixels before we consider something "moving".
# Raise this if camera noise causes false triggers.
FG_PIXEL_THRESHOLD = 500

# How many centroid positions to remember for direction detection.
CENTROID_HISTORY_LEN = 12

# ── Full-frame detection ──────────────────────────────────────────
#
# HOW IT WORKS
# ─────────────
# The whole camera frame is the "cart surface".
# We divide it into two conceptual zones:
#
#   ╔══════════════════════════════════════════╗
#   ║  EDGE ZONE (EDGE_MARGIN_FRACTION wide)   ║
#   ║  ┌────────────────────────────────────┐  ║
#   ║  │                                    │  ║
#   ║  │        INTERIOR ZONE               │  ║
#   ║  │    (products rest here after ADD)  │  ║
#   ║  │                                    │  ║
#   ║  └────────────────────────────────────┘  ║
#   ║  EDGE ZONE                               ║
#   ╚══════════════════════════════════════════╝
#
# ADD:  object enters from the edge zone, moves to interior, settles.
#       After SETTLE_WAIT_SEC, we scan the settled scene -> ADD.
#
# REMOVE: object that was in interior starts moving toward edge,
#         exits the frame (blob disappears at edge).
#         We scan the last frames captured WHILE MOVING -> REMOVE.
#         Only compared against ITEMS ALREADY IN THE CART (faster).
#
# EDGE_MARGIN_FRACTION:
#   What fraction of the frame width/height is considered the "edge zone".
#   0.15 means the outermost 15% on each side.
EDGE_MARGIN_FRACTION = 0.15

# ── ADD confirmation timing ───────────────────────────────────────
# After motion stops and item settles, wait this many seconds before
# scanning. This lets camera autofocus settle and gives a clear still image.
SETTLE_WAIT_SEC = 1.0

# Number of frames to capture during the settled pause for ADD scanning.
ADD_SETTLE_FRAMES = 4

# ── REMOVE scanning ───────────────────────────────────────────────
# How many frames to use from the motion phase for REMOVE matching.
REMOVE_MOTION_FRAMES = 4

# ── Event cooldown ────────────────────────────────────────────────
# Seconds to ignore new motion after an event fires.
EVENT_COOLDOWN_SEC = 1.5

# ── Snapshots ────────────────────────────────────────────────────
# Maximum frames to buffer during the motion phase.
MAX_SNAPSHOTS = 8
