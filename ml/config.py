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
SCORE_THRESHOLD = 0.78

# MARGIN_THRESHOLD:
#   Minimum gap between the #1 and #2 products.
#   A small margin means two products look very similar to the model —
#   we'd rather be cautious and say "uncertain" than guess wrong.
MARGIN_THRESHOLD = 0.06

# ── Multi-frame voting ────────────────────────────────────────────
# How many frames to grab before deciding.
NUM_FRAMES = 5

# How many of those frames must agree on the same product to be "confident".
AGREE_THRESHOLD = 3

# Short pause (seconds) between captured frames so we don't grab
# five frames of the exact same moment.
FRAME_INTERVAL_SEC = 0.12
