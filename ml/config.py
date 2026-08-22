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

# ── Multi-frame voting (ml/multi_frame_vote.py) ───────────────────
# These were referenced by multi_frame_vote.py but had gone missing
# from config — restoring them here so that module imports cleanly.
#
# NUM_FRAMES         how many frames a single burst-vote captures.
# AGREE_THRESHOLD    how many of those frames must independently agree
#                    on the SAME product for the vote to be "confident".
# FRAME_INTERVAL_SEC pause between grabbed frames so we don't collect
#                    near-duplicate images.
#
# The identity tracker below REUSES the same voting logic (via
# multi_frame_vote.vote_over_results) to decide VERIFYING -> CONFIRMED,
# so AGREE_THRESHOLD also controls how much agreement is needed before
# a track's identity is locked.
NUM_FRAMES         = 5
AGREE_THRESHOLD    = 3
FRAME_INTERVAL_SEC = 0.05

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


# ═════════════════════════════════════════════════════════════════
# PERSISTENT-IDENTITY TRACKING  (detector.py, track.py,
#                                identity_tracker.py, cart_state.py)
# ═════════════════════════════════════════════════════════════════
#
# CORE PRINCIPLE (the reason this layer exists):
#   Recognition establishes identity.
#   Tracking preserves identity.
#   Occlusion hides identity — it must NEVER change it.
#   Only a confirmed physical EXIT changes cart state.
#
# Everything below is a named, tunable knob.  Expect to re-tune the
# visibility gates, the exit logic, and the reacquire similarity after
# testing on your own webcam and lighting.
# ─────────────────────────────────────────────────────────────────

# ── Detector (ml/detector.py) ────────────────────────────────────
# MOG2 gives a MOTION / "something changed" signal only — never an
# identity.  These control how the raw foreground mask is turned into
# candidate bounding boxes.
#
# DET_MIN_AREA           smallest blob (px) worth reporting as a candidate.
# DET_MORPH_KERNEL       size of the open/close kernel used to clean speckle.
# DET_WATERSHED_MIN_AREA only blobs LARGER than this are fed to watershed
#                        (splitting is only attempted on big blobs that
#                        might be two touching items — cheap candidate
#                        separation, NOT guaranteed segmentation).
# DET_DT_RATIO           distance-transform threshold (fraction of the per-
#                        blob max) that marks "sure foreground" seeds for
#                        watershed.
#                        DIRECTION MATTERS AND IS COUNTER-INTUITIVE:
#                        HIGHER = splits MORE aggressively.  A high threshold
#                        keeps only the deepest core of each lobe, so two
#                        touching items end up as two separate seeds.  A low
#                        threshold leaves the lobes connected as ONE seed and
#                        nothing is ever split.
#                        Measured on synthetic pairs of round items:
#                          0.45 (old default) never split anything at all
#                          0.65 splits a pair overlapping up to ~15%
#                          0.75 splits up to ~27%
#                        RISK of going higher: a single elongated item (a tall
#                        bottle) can have two distance lobes and get split in
#                        two, which would produce two tracks for one item and
#                        so a DOUBLE COUNT — a false cart change, the one
#                        outcome we care most about avoiding.  Tune this with
#                        your real products in front of the camera and, when
#                        in doubt, go LOWER: a missed second item is a safe
#                        failure, a double count is not.
# DET_LEARNING_RATE      MOG2 background adaptation rate AFTER warm-up.
#                        This is deliberately very low.  MOG2 normally
#                        absorbs a stationary object into the background
#                        within a second or two, after which a placed item
#                        stops being detected at all — and then the first
#                        thing that disturbs it produces a half-blob whose
#                        centroid wanders, which is dangerous input for exit
#                        logic.  Keeping placed items in the foreground is
#                        worth more to us than fast adaptation.
#                        Raise it if slow lighting drift causes phantom
#                        blobs; lower it if placed items stop being detected.
# DET_WARMUP_FRAMES      first N frames use the fast rate below, so the empty
#                        scene is learned quickly at start-up / after R.
# DET_WARMUP_RATE        learning rate during those warm-up frames.
DET_MIN_AREA           = 2500
DET_MORPH_KERNEL       = 5
DET_WATERSHED_MIN_AREA = 14000
DET_DT_RATIO           = 0.65
DET_LEARNING_RATE      = 0.0006
DET_WARMUP_FRAMES      = 40
DET_WARMUP_RATE        = 0.05

# ── Visibility / quality gate (identity_tracker.py) ───────────────
# visibility_ratio = current detected area / this track's LARGEST ever
# observed area.  It is our cheap proxy for "how much of this object is
# currently unoccluded".
#
#   visibility > VISIBILITY_GOOD_RATIO  -> good frame: safe to run the
#                                          matcher and feed the vote.
#   VISIBILITY_WEAK_RATIO .. GOOD        -> weak evidence only; collect but
#                                          never act on it alone.
#   below VISIBILITY_WEAK_RATIO          -> do NOT run recognition at all;
#                                          just update bbox / last_seen.
VISIBILITY_GOOD_RATIO = 0.70
VISIBILITY_WEAK_RATIO = 0.40

# ── Verification -> identity lock (track.py / identity_tracker.py) ─
# VERIFY_MIN_GOOD_FRAMES  how many GOOD-visibility recognitions to gather
#                         before we run the majority vote.  Must be >=
#                         AGREE_THRESHOLD or a lock can never happen.
# EVIDENCE_BUFFER_MAX     cap on the temporary recent_embeddings evidence
#                         buffer (discarded once CONFIRMED).
VERIFY_MIN_GOOD_FRAMES = 5
EVIDENCE_BUFFER_MAX    = 10

# ── Data association: detections <-> existing tracks ──────────────
# A detection is matched to a track using centroid distance + IoU.
#
# ASSOC_MAX_CENTROID_DIST  max centroid distance (px) to allow a match.
# ASSOC_MIN_IOU            IoU at/above which boxes are considered the same
#                          object even if centroids drift.
# ASSOC_AMBIGUOUS_MARGIN   if the best and second-best candidate tracks for
#                          a detection score within this of each other, the
#                          match is "ambiguous" and we fall back to the
#                          LOCKED identity embedding as an appearance
#                          tie-breaker.
# ASSOC_APPEARANCE_WEIGHT  how much appearance counts when it IS consulted.
#                          final = (1-w) * geometry + w * appearance.
#                          Appearance is only consulted for a LOCKED track
#                          that has 2+ competing candidate detections (or a
#                          detection contested by 2+ locked tracks) — i.e.
#                          exactly the overlap situation.  With one item and
#                          one blob, no extra embedding is ever computed.
#                          Raise toward 1.0 to trust appearance more when
#                          items overlap; lower it to trust position more.
ASSOC_MAX_CENTROID_DIST = 140
ASSOC_MIN_IOU           = 0.10
ASSOC_AMBIGUOUS_MARGIN  = 0.12
ASSOC_APPEARANCE_WEIGHT = 0.55

# MERGE_AREA_RATIO
#   When one item is placed against/on another, the detector often reports a
#   SINGLE blob spanning both (watershed cannot always separate them).  If a
#   locked track accepts that union box as its own, its position and size are
#   corrupted: as the other item later moves away, the shrinking blob drags
#   the track's centroid with it, which can look exactly like the track
#   itself moving toward the exit.  That is a false-removal generator.
#   A matched detection larger than this multiple of the track's established
#   size is therefore treated as a MERGED observation: we accept it as proof
#   the item is still there (so it stays counted and does not go LOST) but we
#   refuse to measure position from it.  Same principle as the identity lock,
#   applied to geometry: an ambiguous observation must not change cart state.
#
#   CHOOSING THIS VALUE — both directions cost something:
#     TOO HIGH lets a union blob through and corrupts a locked track's
#       position.  Measured: chawal(160x170) with shampoo(150x215) placed on
#       it gives a union only 1.54x chawal's area.  At 1.6 that passed the
#       guard, and the stationary chawal track was then dragged to the top
#       edge as the shampoo left — it reached EXITING and came within ONE
#       frame of a false REMOVE.  That is the worst outcome we have.
#     TOO LOW freezes a track's size baseline.  The baseline only ever grows
#       by this factor per frame, so an item first seen partly covered can
#       end up permanently rejecting its own true full-size box, sitting at
#       visibility 0 in OCCLUDED/LOST.  It STILL COUNTS in the cart, and the
#       cost is a possibly-missed later removal — an "uncertain", which is
#       the safe failure.
#   1.35 is chosen accordingly: it catches the two-rectangle union above with
#   margin, and it errs toward the failure that cannot invent or delete cart
#   items.  Deliberately no escape hatch for a long-lived merge: re-basing the
#   baseline after N merged frames would just re-corrupt the geometry of two
#   items that genuinely sit together for a while.
MERGE_AREA_RATIO = 1.35

# ── Occlusion / lost / reacquire (track.py) ───────────────────────
# OCCLUDED_TO_LOST_FRAMES  frames a PRESENT/OCCLUDED track can go with no
#                          matching detection before we mark it LOST.
#                          (LOST still counts in the cart — it is presumed
#                           physically present, just not currently tracked.)
# UNCONFIRMED_PRUNE_FRAMES tracks that were NEVER confirmed (still NEW /
#                          VERIFYING) may be pruned after this many unseen
#                          frames — they never became cart items, so
#                          dropping them changes nothing in the cart.
# REACQUIRE_SIMILARITY     min cosine similarity between a new detection's
#                          appearance embedding and a LOST track's LOCKED
#                          identity_embedding to re-bind them (LOST ->
#                          REACQUIRE -> PRESENT).
# REACQUIRE_MAX_DIST       how far (px) from a LOST track's last position a
#                          detection may appear and still be considered a
#                          plausible reacquisition.
OCCLUDED_TO_LOST_FRAMES  = 18
UNCONFIRMED_PRUNE_FRAMES = 12
REACQUIRE_SIMILARITY     = 0.60
REACQUIRE_MAX_DIST       = 240

# ── Exit detection: the ONLY path that removes an item ────────────
# A confirmed track is removed from the cart ONLY when it travels toward
# and across the exit boundary consistently over several frames.  A track
# that merely disappears goes to OCCLUDED/LOST instead — never REMOVED.
#
# EXIT_BOUNDARY_MARGIN   width (px) of the border band treated as the exit
#                        zone.  A centroid inside this band near a frame
#                        edge is "at the boundary".
# MOVING_MIN_DISPLACEMENT centroid movement (px/frame) above which a track
#                        is considered MOVING rather than settled/PRESENT.
# EXIT_CONFIRM_FRAMES    consecutive frames of boundary-directed motion
#                        required to go MOVING -> EXITING, and then the
#                        track must actually leave the frame to be REMOVED.
EXIT_BOUNDARY_MARGIN    = 45
MOVING_MIN_DISPLACEMENT = 7
EXIT_CONFIRM_FRAMES     = 3

# EXIT_CLIP_MARGIN
#   An item on its way out of frame gets CLIPPED by the frame edge, so its
#   detected area shrinks — which looks identical to "something is covering
#   it" if you only measure area.  That ambiguity is what makes a leaving
#   item get filed as OCCLUDED and never removed.
#   A box whose edge sits within this many px of the zone boundary is treated
#   as clipped BY the boundary, so its shrinkage is explained by leaving
#   rather than by occlusion.  This only applies to a track that has ALREADY
#   built up outward-motion evidence (exit_progress > 0 / EXITING); a
#   stationary item sitting near the edge that gets covered still goes to
#   OCCLUDED, so the safety property is untouched.
EXIT_CLIP_MARGIN = 8

# DEOCCLUSION_VIS_JUMP
#   When an occluder moves off an item, the item's box suddenly grows back to
#   full size and its centroid jumps — with the item never having moved.
#   If visibility rises by more than this in one frame, that frame's
#   displacement is treated as an artefact and is not allowed to count as
#   motion toward the exit.
DEOCCLUSION_VIS_JUMP = 0.22

# ── Detection zone (identity_tracker.py / UI) ─────────────────────
# The active "cart surface" region as a fraction of the frame
# (left, top, right, bottom).  Detections whose centroid is outside this
# zone are ignored.  Crossing OUT of this zone is what counts as an exit.
# Defaults cover almost the whole frame with a thin border = the exit band.
ZONE_LEFT   = 0.03
ZONE_TOP    = 0.03
ZONE_RIGHT  = 0.97
ZONE_BOTTOM = 0.97
