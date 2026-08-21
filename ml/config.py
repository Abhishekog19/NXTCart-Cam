# ---------------------------------------------------------------
# ml/config.py  –  ALL tuneable parameters live here.
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
# Root directory where you store reference photos.
# Structure: references/<product_name>/<any_image>.jpg
REFERENCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")

# Where the pre-computed embedding database is saved.
# build_db.py writes it; demo.py and matcher.py read it.
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embedding_db.pkl")

# Where the TFLite model file will be stored after the first download.
MODEL_PATH = os.path.join(os.path.dirname(__file__), "mobilenet_v2_quant.tflite")

# ── Model input ──────────────────────────────────────────────────
# MobileNetV2 expects 224×224 RGB images, values in [-1, 1].
IMAGE_SIZE = 224

# ── Matching thresholds ──────────────────────────────────────────
# SCORE_THRESHOLD:
#   Minimum cosine similarity the best-matching reference must reach
#   for any "confident" call.  Cosine similarity runs from -1 to 1;
#   products are typically 0.70–0.95 for a good match.
#   Start here and tune down if you get too many "uncertain" hits.
SCORE_THRESHOLD = 0.55

# MARGIN_THRESHOLD:
#   Minimum gap between the #1 and #2 products.
#   A small margin means two products look very similar to the model —
#   we'd rather be cautious and say "uncertain" than guess wrong.
MARGIN_THRESHOLD = 0.03

# ── Multi-frame voting ────────────────────────────────────────────
# How many frames to grab before deciding.
NUM_FRAMES = 5

# How many of those frames must agree on the same product to be "confident".
AGREE_THRESHOLD = 3

# Short pause (seconds) between captured frames so we don't grab
# five frames of the exact same moment.
FRAME_INTERVAL_SEC = 0.12

# ── Zone tracker (background-subtraction cart gate) ───────────────
#
# ZONE_RECT defines the gateway rectangle in the camera frame.
# Format: (x, y, width, height) in pixels, measured from top-left.
#
# HOW TO FIND YOUR VALUES:
#   Run live_cart_demo.py and look at the green rectangle drawn on
#   screen.  Adjust these four numbers until the rectangle sits
#   exactly over the opening of your box / gateway.
#
# Default: centred third of a typical 640×480 feed.
ZONE_RECT = (180, 120, 280, 240)   # (x, y, w, h)

# Background subtractor model choice: 'MOG2' or 'KNN'.
# MOG2 is faster; KNN can handle more lighting variation.
BGS_METHOD = "MOG2"

# How quickly the background model adapts to new static content.
# Lower = faster adaptation (settled items disappear from foreground sooner).
# Range roughly 0.001 – 0.01.  0.005 is a good starting point.
BGS_LEARNING_RATE = 0.005

# Minimum number of foreground pixels inside the zone to be considered
# "something is moving".  Raise this if you get false triggers from
# lighting flicker; lower it if slow-moving objects are missed.
FG_PIXEL_THRESHOLD = 250

# How many centroid positions to keep in memory when tracking a crossing.
# 5–10 frames is plenty for direction detection.
CENTROID_HISTORY_LEN = 8

# The zone rectangle is divided into a top band and a bottom band to
# determine direction of travel:
#
#  ┌─────────────────────────┐  ← zone top (y = ZONE_RECT[1])
#  │   OUTSIDE / ABOVE       │  ← y-fraction < ENTRY_Y_FRACTION
#  │─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
#  │   INSIDE / BELOW        │  ← y-fraction >= ENTRY_Y_FRACTION
#  └─────────────────────────┘  ← zone bottom
#
# If centroid starts in the top band and ends in the bottom band → ADD
# If centroid starts in the bottom band and ends in the top band → REMOVE
#
# ENTRY_Y_FRACTION = 0.4 means the dividing line is 40% down the zone.
ENTRY_Y_FRACTION = 0.4

# Cooldown in seconds after a resolved event before the tracker accepts
# a new crossing.  Prevents a single slow movement being counted twice.
EVENT_COOLDOWN_SEC = 0.4

# How many frames captured during a crossing to keep as candidate
# snapshots for product identification.
MAX_SNAPSHOTS = 6
