# ---------------------------------------------------------------
# ml/config.py  --  ALL tuneable parameters live here.
# ---------------------------------------------------------------

import os

# ── Webcam ──────────────────────────────────────────────────────
CAMERA_INDEX = 0

# ── Paths ────────────────────────────────────────────────────────
REFERENCES_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")
DATABASE_PATH   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embedding_db.pkl")
MODEL_PATH      = os.path.join(os.path.dirname(__file__), "mobilenet_v2_quant.tflite")
ONNX_MODEL_PATH = os.path.join(os.path.dirname(__file__), "mobilenet_v2.onnx")

# ── Model ────────────────────────────────────────────────────────
IMAGE_SIZE = 224

# EMBEDDING_BACKEND — which runtime computes the 1280-D embedding.
#   "auto"    try the fast ONNX/cv2.dnn path, fall back to TFLite (default)
#   "onnx"    ONNX only; fail loudly rather than silently running slow
#   "tflite"  the legacy quantized path only
#
# WHY THERE IS A CHOICE AT ALL: the TFLite runtime on this platform
# (ai-edge-litert 2.2.0 / Python 3.14 / Windows) segfaults with XNNPACK and
# segfaults with num_threads > 1, leaving only its slowest configuration —
# 1619 ms per call, which made the live demo untestable.  The same network
# as float ONNX through cv2.dnn measures 6.5 ms with equal accuracy
# (leave-one-out 19/20 either way).  See ml/embedding_extractor.py.
#
# The two backends produce DIFFERENT, incompatible embedding spaces, so
# changing this REQUIRES rebuilding the database:  python build_db.py
# (build_db stamps the backend into the pickle and matcher.py refuses a
# mismatch, so a forgotten rebuild is an error, never silent nonsense.)
EMBEDDING_BACKEND = "auto"

# ── Matching ─────────────────────────────────────────────────────
# Minimum cosine similarity for a match to count.
# Raise this if you see wrong products being identified.
#
# 0.72 comes from a grid search over references/ plus 20 unknown objects,
# using the ONNX embedding space and the _MARGIN_THRESHOLD = 0.03 in
# ml/matcher.py:
#     17/20 true accepts, 0 WRONG, and 0/20 unknown objects falsely locked.
# The previous 0.62 falsely locked 2/20 unknown objects — i.e. it would
# invent a product for something that is not in the database at all, which
# is the expensive kind of mistake.  Raise it further if you still see
# wrong names; lower it if real items refuse to lock.
SCORE_THRESHOLD = 0.72

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

# ── PER-FRAME INFERENCE BUDGET ────────────────────────────────────
# WHY THIS EXISTS
#   _try_verify used to run recognition on EVERY unlocked track EVERY frame.
#   In real footage 5-8 junk candidates (hands, shadows, partial blobs) are
#   alive at once, so a single frame paid for 5-8 inferences.  At the old
#   1619 ms per call that was 8-13 SECONDS per frame.  Even at 6.5 ms it has
#   to be bounded or a crowded frame still stutters.
#
#   The caps are per-frame COUNTS, not a time budget, deliberately:
#   process() must stay deterministic so test_scripted.py can replay an
#   exact frame sequence and get an identical result.  A wall-clock budget
#   would make the outcome depend on machine load.
#
#   Worst case per frame = 3 + 1 + 1 = 5 embeddings ~= 32 ms.
#   Typical case (one item settling) = 1-2 embeddings ~= 6-13 ms.
#
# VERIFY_MAX_PER_FRAME       unlocked tracks that may be recognised per frame.
#                            When several are eligible, the one chosen is
#                            decided by a fixed key — fewest attempts so far
#                            (round-robin, so no track is starved and the
#                            worst-case time-to-lock stays bounded), then
#                            highest visibility, then lowest track_id.
# ASSOC_EMBED_MAX_PER_FRAME  detections that may be embedded for the
#                            appearance tie-break during association.
# REACQUIRE_MAX_PER_FRAME    unmatched detections that may be embedded while
#                            trying to reacquire a LOST track.
VERIFY_MAX_PER_FRAME      = 1
ASSOC_EMBED_MAX_PER_FRAME = 3
REACQUIRE_MAX_PER_FRAME   = 1

# ── "SETTLED" GATE FOR VERIFICATION ───────────────────────────────
# An inference is only worth paying for on a frame where the answer can be
# trusted.  Recognising an item WHILE it is being carried — moving, tilted,
# half-covered by the hand holding it — is what produced the garbage votes
# and the conf=0.30 locks in the logs.  So a track must have stopped moving
# before we spend anything on it.
#
# This is a speed fix and an accuracy fix at the same time: hands and
# shadows are almost never still AND clean, so they drop out of the
# inference pool entirely.
#
# VERIFY_MIN_STILL_FRAMES  consecutive frames with displacement below
#                          MOVING_MIN_DISPLACEMENT before recognition may run.
#                          Keep small — this delays every lock by that many
#                          frames (2 frames ~= 70 ms at 30 fps).
# VERIFY_MIN_QUALITY       detection-level quality floor (solidity).  A ragged
#                          sliver of a blob is not worth an inference.
VERIFY_MIN_STILL_FRAMES = 2
VERIFY_MIN_QUALITY      = 0.45

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
#
#                          KNOWN WEAKNESS, left alone on purpose: in the
#                          ONNX embedding space similarities compress into
#                          roughly 0.6-0.9, so `(1-w)*geo + w*sim` adds a
#                          near-constant offset to every contended pair and
#                          discriminates only weakly between them.
#                          Rescaling similarity WITHIN the contended set
#                          (min-max across just those pairs) would fix it,
#                          but that changes association accuracy and belongs
#                          in its own change with its own overlap testing.
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
#                          0.80, not 0.60.  The old value sat BELOW the
#                          measured similarity ceiling for unknown objects
#                          (0.632), so reacquisition accepted almost
#                          anything — the live logs showed reacquires firing
#                          at sim=0.638 / 0.652 / 0.682, barely above the
#                          noise floor.  This comparison is far easier than
#                          general recognition: it matches a detection
#                          against ONE specific instance of the same
#                          physical item in the same lighting, so it should
#                          score much higher than a cross-product match.
#                          TUNE THIS FIRST from the live log — every
#                          reacquire prints its sim=.
# REACQUIRE_MAX_DIST       how far (px) from a LOST track's last position a
#                          detection may appear and still be considered a
#                          plausible reacquisition.
OCCLUDED_TO_LOST_FRAMES  = 18
UNCONFIRMED_PRUNE_FRAMES = 12
REACQUIRE_SIMILARITY     = 0.80
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

# EXIT_EVIDENCE_GRACE_FRAMES
#   How many consecutive no-detection frames a track may have WITHOUT losing
#   its accumulated exit_progress.
#
#   Why this is needed: removing an item means putting a hand over it.  The
#   hand merges with or covers the item, the track goes unmatched, and
#   _update_unmatched used to zero exit_progress on the spot — erasing the
#   evidence of the very departure it was collecting, before it could reach
#   EXIT_CONFIRM_FRAMES.  A removal could therefore almost never complete.
#
#   Scope is deliberately narrow: this grace applies ONLY to the
#   "no detection at all" case, where nothing can corrupt the track's
#   geometry because nothing was measured.  It does NOT apply to
#   Track.note_merged_frame (a merged blob CAN drag a stationary track
#   toward the edge — that reset is what stopped a measured near-false
#   REMOVE) nor to the low-visibility reset in _locked_state_machine (a
#   stationary item being covered up should lose its progress).
EXIT_EVIDENCE_GRACE_FRAMES = 2

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

# ═════════════════════════════════════════════════════════════════
# STATIC PRESENCE CHECK  (identity_tracker.py / detector.py)
# ═════════════════════════════════════════════════════════════════
#
# THE PROBLEM THIS SOLVES
#   MOG2 reports MOTION, not objects.  An item that has been put down and
#   left alone stops producing detections, so its track slid
#   PRESENT -> OCCLUDED -> LOST while the item was still sitting there in
#   plain view.  Staying counted in the cart was correct, but the cost was
#   severe: a LOST track is not in _MATCHABLE and is skipped by
#   unmatched_tracks, so it can never again accumulate the outward-motion
#   evidence that EXITING -> REMOVED requires.  Sliding that item away
#   therefore could not remove it.
#
#   The old code had no way to ask "is the item still there?" — presence was
#   inferred purely from "did MOG2 see motion here", which is the wrong
#   question about a stationary object.
#
# WHAT WE DO INSTEAD
#   For a LOCKED track that got no detection this frame, compare the CURRENT
#   pixels in its own box against two references:
#     1. a small grayscale template of the item, saved when we could see it
#        clearly, and
#     2. the same box taken from MOG2's learned background image
#        (cv2.BackgroundSubtractor.getBackgroundImage()).
#   Both comparisons use normalised cross-correlation (TM_CCOEFF_NORMED),
#   which is brightness/contrast invariant and costs well under a
#   millisecond on a 64px patch.
#
#     looks like the item        -> STILL THERE: stay PRESENT
#     looks like the background  -> VACATED:     count a departure frame
#     looks like neither         -> OCCLUDED:    something is on top of it
#
#   "Neither" defaulting to occlusion keeps the safety property: ambiguity
#   never removes a cart item.
#
# PRESENCE_ITEM_MATCH      correlation with the item's own template at or
#                          above which the item is judged still present.
# PRESENCE_BG_MATCH        correlation with the learned background at or
#                          above which the spot is judged empty.  BOTH this
#                          AND a below-PRESENCE_ITEM_MATCH item score are
#                          required to call a frame vacated.
# PRESENCE_VACATED_FRAMES  consecutive vacated frames before the track is
#                          REMOVED.  Any single non-vacated frame resets the
#                          count to zero.  This is the new removal path, and
#                          it is stronger evidence than tracked motion: it is
#                          direct proof the item is no longer where it was,
#                          observable even though the hand was covering the
#                          item during the entire departure.
#                          Raise it if lighting flicker ever causes a
#                          phantom removal; lower it for snappier removals.
# PRESENCE_TEMPLATE_PX     the item template and the ROI are both resized to
#                          this square before correlating, so the comparison
#                          is cheap and size-independent.
PRESENCE_ITEM_MATCH     = 0.55
PRESENCE_BG_MATCH       = 0.60
PRESENCE_VACATED_FRAMES = 5
PRESENCE_TEMPLATE_PX    = 64

# ── Detection zone (identity_tracker.py / UI) ─────────────────────
# The active "cart surface" region as a fraction of the frame
# (left, top, right, bottom).  Detections whose centroid is outside this
# zone are ignored.  Crossing OUT of this zone is what counts as an exit.
# Defaults cover almost the whole frame with a thin border = the exit band.
ZONE_LEFT   = 0.03
ZONE_TOP    = 0.03
ZONE_RIGHT  = 0.97
ZONE_BOTTOM = 0.97


# ═════════════════════════════════════════════════════════════════
# BARCODE-GATED VERIFICATION  (frame_source / item_follower /
#                              visibility / verifier / custody)
# ═════════════════════════════════════════════════════════════════
#
# THIS IS A DIFFERENT PIPELINE from the persistent-identity tracker above.
# The tracker answers "what is on the surface and did it leave?" as an
# open-set problem.  The verification pipeline answers a much narrower,
# far more reliable question, gated by a barcode scan:
#
#       "The scanner says this is SKU X.  Is the item I watched travel
#        from the scanner into the cart ACTUALLY X — yes / no / unsure?"
#
# Turning recognition into a 1-vs-1 test is what makes it trustworthy, and
# it is the only thing that can catch the attack weight cannot: scanning a
# cheap item and dropping in a same-weight expensive one.  Appearance +
# colour, checked on the SAME crops, are the two independent channels.
#
# Everything here errs toward RETRY / SUSPECT / MISMATCH.  No knob and no
# code path is allowed to turn ambiguity into acceptance.

# ── Frame source (ml/frame_source.py) ─────────────────────────────
# CAMERA_SOURCE   which FrameSource verify_demo.py builds:
#                   "webcam"  local device via FrameGrabber  (tonight)
#                   "mjpeg"   ESP32-CAM HTTP stream           (tomorrow)
# ESP32_STREAM_URL MJPEG/HTTP URL of the ESP32-CAM when CAMERA_SOURCE=mjpeg.
#                  Typically http://<cam-ip>:81/stream .  Ignored otherwise.
CAMERA_SOURCE    = "webcam"
ESP32_STREAM_URL = "http://192.168.4.1:81/stream"

# ── Spatial regions for the scan→cart journey (frame fractions) ───
# SCANNER_REGION    where an item first appears after being scanned; the
#                   follower LOCKS the first qualifying item whose centroid
#                   is inside this box.  (left, top, right, bottom).
# CART_ENTRY_REGION reaching this region is the spatial half of the "the
#                   item actually went into the cart" gate.  The camera sits
#                   opposite the scanner, so by default the item travels from
#                   one side of the frame to the other.
# These are deliberately generous defaults; retune once the ESP32-CAM is
# mounted and the real geometry is known.
SCANNER_REGION    = (0.00, 0.00, 0.45, 1.00)   # left side of frame
CART_ENTRY_REGION = (0.55, 0.00, 1.00, 1.00)   # right side of frame

# ── Crop collection across the trajectory (item_follower.py) ──────
# VERIFY_BURST_FRAMES  max clean crops kept for one transaction.  Crops are
#                      SAMPLED across the whole movement (not just the last
#                      few), each downscaled to IMAGE_SIZE, so the memory
#                      cost is bounded (~VERIFY_BURST_FRAMES * 224*224*3 B).
# VERIFY_MIN_USABLE_FRAMES  fewest usable crops before a verdict may be
#                      anything other than RETRY.  Too few clean views of the
#                      item = not enough evidence = ask the shopper to redo it.
VERIFY_BURST_FRAMES      = 12
VERIFY_MIN_USABLE_FRAMES = 3

# ── Follower continuity (item_follower.py) ────────────────────────
# VERIFY_LOST_GRACE_FRAMES  consecutive frames the locked target may go with
#                           no acceptable detection before the follower gives
#                           up and the transaction becomes RETRY.  (The item
#                           was briefly occluded by the hand — allow a little,
#                           but a real loss of continuity must not be papered
#                           over, so this is small.)
VERIFY_LOST_GRACE_FRAMES = 6

# ── Verifier thresholds (ml/verifier.py) ──────────────────────────
# THESE ARE ABSOLUTE, NOT RANK-BASED.  With a single expected SKU the
# matcher's "top match == expected" is vacuously true, so it proves nothing;
# a raw similarity floor is the only thing that actually tests the hypothesis.
#
# VERIFY_APPEARANCE_THRESHOLD  min cosine similarity between a live crop's
#                     embedding and the expected SKU's BEST reference for that
#                     crop to count as an appearance "pass".  Seeded from
#                     SCORE_THRESHOLD (0.72), the measured operating point of
#                     the ONNX embedding space, and retuned tomorrow on real
#                     products / the deployment camera.
# VERIFY_COLOR_THRESHOLD  min colour-histogram similarity (same metric as
#                     ColorCodeRecognizer) between a live crop and the SKU's
#                     BEST colour reference to count as a colour "pass".
#                     Colour is a coarse channel, so this is a target to be
#                     tuned tomorrow; it exists to catch the same-weight,
#                     different-colour swap, not to make fine distinctions.
# VERIFY_PASS_FRACTION  fraction of usable crops that must pass a channel for
#                     that channel to be considered satisfied overall.  This
#                     is the multi-view smoothing: one bad frame cannot fail a
#                     good item and one lucky frame cannot pass a wrong one.
VERIFY_APPEARANCE_THRESHOLD = 0.72
VERIFY_COLOR_THRESHOLD      = 0.55
VERIFY_PASS_FRACTION        = 0.50

# ── Transaction gating (ml/custody.py) ────────────────────────────
# VERIFY_TXN_TIMEOUT_SEC  wall-clock budget for one scan→verify transaction.
#                     If the item never reaches the cart region, or the weight
#                     never changes-and-settles within this long, the
#                     transaction resolves RETRY instead of hanging.  A demo
#                     value; retune with the real weight-settle latency.
VERIFY_TXN_TIMEOUT_SEC = 12.0

# ── Usable-view test (ml/visibility.py) ───────────────────────────
# "Is there enough of a PRODUCT in this crop to judge it?"  Decided from
# several cues together so that a low-saturation product (white/beige
# packaging) is NOT mistaken for an empty / occluded view:
#
# VIS_MIN_CROP_PX  smallest side (px) of a crop worth judging.  (Reuses the
#                  spirit of MIN_CROP_PX above; kept separate so the verify
#                  path can be tuned without touching the scene-compare path.)
# VIS_TEXTURE_MIN  minimum grayscale standard deviation.  A flat, textureless
#                  patch (a hand, a blank surface, motion blur) sits below
#                  this; a real product's print/edges sit above it.  This is
#                  the cue that does NOT depend on colour, so it is what keeps
#                  a white box from being called invisible.
# VIS_EDGE_MIN     minimum Laplacian energy (edge content), a second
#                  colour-independent cue for the same reason.
VIS_MIN_CROP_PX = 60
VIS_TEXTURE_MIN = 12.0
VIS_EDGE_MIN    = 8.0
