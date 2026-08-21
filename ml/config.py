# ---------------------------------------------------------------
# ml/config.py  --  ALL tuneable parameters live here.
# ---------------------------------------------------------------

import os

# ── Webcam ──────────────────────────────────────────────────────
CAMERA_INDEX = 0

# ── Paths ────────────────────────────────────────────────────────
REFERENCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")
DATABASE_PATH  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embedding_db.pkl")
MODEL_PATH     = os.path.join(os.path.dirname(__file__), "mobilenet_v2_quant.tflite")

# ── Model ────────────────────────────────────────────────────────
IMAGE_SIZE = 224

# ── Matching ─────────────────────────────────────────────────────
# Minimum cosine similarity for a match to count.
# Raise this if you see wrong products being identified.
SCORE_THRESHOLD = 0.62

# ── Background subtractor ─────────────────────────────────────────
# MOG2 is faster; KNN handles more lighting variation.
BGS_METHOD = "MOG2"

# How quickly the background model adapts.
# Lower = absorbs stationary objects into background faster.
BGS_LEARNING_RATE = 0.004

# ─────────────────────────────────────────────────────────────────
# SCENE-STATE COMPARISON PARAMETERS
# ─────────────────────────────────────────────────────────────────
#
# HOW THE DETECTION WORKS
# ────────────────────────
# Instead of tracking which way items moved (unreliable), we:
#
#   1. Wait for the scene to be perfectly still   → "BEFORE" snapshot
#   2. Detect when someone disturbs the scene     → DISTURBED
#   3. Wait for the scene to go still again       → "AFTER" snapshot
#   4. Compare BEFORE vs AFTER pixel-by-pixel:
#        - Regions that have texture in AFTER but not BEFORE → ADD
#        - Regions that have texture in BEFORE but not AFTER → REMOVE
#        - Same item in both → repositioned (no cart change)
#   5. Scan only the changed region crops (not the full frame)
#      → smaller, focused crops = better accuracy
#
# This approach is:
#   • Direction-agnostic  (no hand vs. item confusion)
#   • Multi-item capable  (each contour = one potential event)
#   • Immune to repositioning false alarms
# ─────────────────────────────────────────────────────────────────

# How many consecutive still frames needed to declare the scene "settled".
# At ~20-30 fps, 20 frames ≈ 0.7-1 second of stillness.
STABLE_FRAMES_REQUIRED = 20

# Frames of background learning before the tracker starts (initial warm-up).
LEARNING_FRAMES = 50

# Frames of still scene to average together for the before/after snapshots.
# Averaging multiple frames reduces sensor noise, giving cleaner comparisons.
BEFORE_BUFFER_FRAMES = 5

# Pixel brightness difference (0-255) needed to count a pixel as "changed".
# Raise this if lighting flicker causes false change detections.
DIFF_THRESHOLD = 30

# Minimum area (pixels) of a connected changed region to be worth processing.
# Smaller contours are treated as noise and ignored.
MIN_REGION_AREA = 3500

# Grayscale standard deviation of a crop to be classified as "has an item".
# Used only as a MINIMUM floor — the ratio check below is the primary signal.
TEXTURE_STD_THRESHOLD = 10

# RATIO-based ADD/REMOVE classification.
# We compare std_after / std_before (and its inverse).
#
#   ADD:    std_after  / std_before  > TEXTURE_RATIO_THRESHOLD  (item appeared)
#   REMOVE: std_before / std_after   > TEXTURE_RATIO_THRESHOLD  (item disappeared)
#   SWAP:   ratio close to 1.0                                  (item repositioned)
#
# Using a ratio makes the system independent of how textured your surface is.
# Your data showed: empty→item = ratio 3.0, item→item = ratio 1.0-1.1.
# 1.8 cleanly separates these two cases.
TEXTURE_RATIO_THRESHOLD = 1.8


# Minimum size of a crop (pixels in each dimension) to attempt scanning.
MIN_CROP_PX = 80

# ── Motion detection ─────────────────────────────────────────────
# Foreground pixel count above which we declare "scene is disturbed".
# Raise if camera noise causes false triggers; lower if items aren't detected.
FG_PIXEL_THRESHOLD = 500

# ── Cooldown ─────────────────────────────────────────────────────
# Seconds to ignore motion after an event fires.
# Must be long enough that the hand fully exits the frame.
EVENT_COOLDOWN_SEC = 2.5
