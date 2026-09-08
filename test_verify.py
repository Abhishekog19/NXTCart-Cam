# ---------------------------------------------------------------
# test_verify.py  --  HEADLESS BRANCH COVERAGE (no camera, no model)
#
# WHAT THIS PROVES  (read this first)
# ────────────────────────────────────
# Tonight there is no hardware and no reference photos, so we cannot prove
# RECOGNITION ACCURACY — that is tomorrow's job on real products.  What we
# CAN prove tonight is that the CONTROL LOGIC is correct: that every verdict
# branch is reachable and is reached for the right reason.
#
# The trick that makes this possible without a model or a camera:
#   • a StubRecognizer whose appearance similarity is a number WE set, and
#   • a colour histogram function whose colour similarity is a number WE set,
# INDEPENDENTLY.  That lets us drive the verifier into each cell of its truth
# table on demand — including the subtle "colour passes while appearance
# fails" cell — instead of hoping a real image happens to land there.
#
# The follower is exercised with the OracleDetector (scripted detections),
# so lock / ambiguous / merged / lost / reached-cart and the seq-dedupe rule
# are each hit deterministically.
#
# Run:  python test_verify.py       (exits non-zero if any check fails)
# ---------------------------------------------------------------

from __future__ import annotations

import sys

import numpy as np

from ml.config import (
    ASSOC_AMBIGUOUS_MARGIN,
    MERGE_AREA_RATIO,
    VERIFY_APPEARANCE_THRESHOLD,
    VERIFY_COLOR_THRESHOLD,
    VERIFY_LOST_GRACE_FRAMES,
    VERIFY_MIN_USABLE_FRAMES,
    VERIFY_PASS_FRACTION,
)
from ml.detector import Detection
from ml.frame_source import FrameMeta
from ml.item_follower import FollowStatus, ItemFollower
from ml.verifier import ColourReference, ProductVerifier, Verdict, colour_hist

# ── a textured crop that ml.visibility.assess() will call usable ──────
# Random noise has high grayscale std and high Laplacian energy, so it
# clears both visibility cues — it stands in for "a clear view of a product"
# without needing a real photo.
_RNG = np.random.default_rng(0)


def _usable_crop(size: int = 96) -> np.ndarray:
    return _RNG.integers(0, 256, size=(size, size, 3), dtype=np.uint8)


# ═════════════════════════════════════════════════════════════════
# STUBS: independently controlled appearance + colour scores
# ═════════════════════════════════════════════════════════════════

class StubRecognizer:
    """
    A recognizer whose appearance similarity is whatever we say it is.

    embed() returns a throwaway vector; similarity() ignores its arguments
    and returns the fixed appearance score.  This decouples the appearance
    channel from any real image content so tests can target a branch exactly.
    """

    def __init__(self, appearance_score: float) -> None:
        self.appearance_score = appearance_score

    def embed(self, crop: np.ndarray) -> np.ndarray:
        return np.zeros(4, dtype=np.float32)

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return self.appearance_score


def _make_verifier(appearance_score: float, colour_score: float,
                   sku: str = "sku_a", has_colour_ref: bool = True):
    """
    Build a ProductVerifier wired so appearance and colour each resolve to a
    known score regardless of the actual crop.
    """
    recog = StubRecognizer(appearance_score)
    # One appearance reference (its content is irrelevant — similarity is
    # stubbed), so the SKU is "in the database".
    appearance_db = {sku: [np.zeros(4, dtype=np.float32)]}

    # Colour: a ColourReference whose best_similarity returns colour_score for
    # any crop hist.  We achieve that with a 1-D hist of [colour_score] and a
    # colour_hist_fn that returns [1.0] — their dot product is colour_score.
    colour_db = {}
    if has_colour_ref:
        ref = ColourReference([np.array([colour_score], dtype=np.float32)])
        colour_db = {sku: ref}

    def colour_hist_fn(crop):
        return np.array([1.0], dtype=np.float32)

    return ProductVerifier(recog, appearance_db=appearance_db,
                           colour_db=colour_db, colour_hist_fn=colour_hist_fn)


# ═════════════════════════════════════════════════════════════════
# tiny assert harness
# ═════════════════════════════════════════════════════════════════

_failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


# ═════════════════════════════════════════════════════════════════
# VERIFIER TRUTH TABLE
# ═════════════════════════════════════════════════════════════════

def test_verifier_truth_table():
    print("\n[verifier] verdict truth table")
    crops = [_usable_crop() for _ in range(VERIFY_MIN_USABLE_FRAMES + 1)]

    hi_app = VERIFY_APPEARANCE_THRESHOLD + 0.1
    lo_app = VERIFY_APPEARANCE_THRESHOLD - 0.2
    hi_col = VERIFY_COLOR_THRESHOLD + 0.1
    lo_col = VERIFY_COLOR_THRESHOLD - 0.2

    # appearance pass + colour pass -> MATCH
    r = _make_verifier(hi_app, hi_col).verify("sku_a", crops)
    check("MATCH  (app pass, col pass)", r.verdict == Verdict.MATCH, r.verdict)
    check("MATCH is the only accepting verdict", r.accepted, str(r.accepted))

    # appearance pass + colour fail -> SUSPECT  (the same-weight swap)
    r = _make_verifier(hi_app, lo_col).verify("sku_a", crops)
    check("SUSPECT (app pass, col fail)", r.verdict == Verdict.SUSPECT, r.verdict)
    check("SUSPECT does not accept", not r.accepted, str(r.accepted))

    # appearance fail + colour pass -> MISMATCH (colour alone never accepts)
    r = _make_verifier(lo_app, hi_col).verify("sku_a", crops)
    check("MISMATCH (app fail, col pass)", r.verdict == Verdict.MISMATCH, r.verdict)

    # appearance fail + colour fail -> MISMATCH
    r = _make_verifier(lo_app, lo_col).verify("sku_a", crops)
    check("MISMATCH (app fail, col fail)", r.verdict == Verdict.MISMATCH, r.verdict)

    # too few usable crops -> RETRY
    few = [_usable_crop() for _ in range(VERIFY_MIN_USABLE_FRAMES - 1)]
    r = _make_verifier(hi_app, hi_col).verify("sku_a", few)
    check("RETRY (too few usable crops)", r.verdict == Verdict.RETRY, r.verdict)

    # follower_broken -> RETRY regardless of crop content
    r = _make_verifier(hi_app, hi_col).verify("sku_a", crops, follower_broken=True)
    check("RETRY (follower broken)", r.verdict == Verdict.RETRY, r.verdict)

    # SKU absent from DB -> UNAVAILABLE
    r = _make_verifier(hi_app, hi_col).verify("no_such_sku", crops)
    check("UNAVAILABLE (SKU not in DB)", r.verdict == Verdict.UNAVAILABLE, r.verdict)

    # A SKU with NO colour reference can never reach MATCH (safe direction):
    # colour cannot pass, so a perfect appearance resolves SUSPECT at best.
    r = _make_verifier(hi_app, hi_col, has_colour_ref=False).verify("sku_a", crops)
    check("no colour ref -> SUSPECT not MATCH", r.verdict == Verdict.SUSPECT, r.verdict)


# ═════════════════════════════════════════════════════════════════
# FOLLOWER STATE MACHINE  (scripted geometry)
# ═════════════════════════════════════════════════════════════════

FRAME_W, FRAME_H = 640, 480
# SCANNER_REGION is the left 45%, CART_ENTRY_REGION the right 45% (config).
# The cart-entry region starts at x=0.55*640=352, so a box whose centroid
# crosses x=352 (box x >= 312 for an 80px box) counts as reached.
SCANNER_X = 40      # inside the scanner region
CART_X = 340        # box x=340 -> centroid 380, inside the cart-entry region

# Association tolerates a centroid jump up to ASSOC_MAX_CENTROID_DIST (140px)
# and rewards IoU overlap; a 60px step per frame stays well inside both, so a
# smooth left→right transit associates every frame the way a real item would.
_STEP = 60


def _det(x, y=200, w=80, h=80, quality=1.0):
    return Detection(bbox=(x, y, w, h), mask=None, quality=quality)


def _transit_xs(start=SCANNER_X, end=CART_X, step=_STEP):
    """Box x-positions for a smooth left→right transit, ending in the cart."""
    xs = list(range(start, end, step))
    xs.append(end)
    return xs


def _meta(seq):
    return FrameMeta(seq=seq, ts=float(seq))


def _frame():
    # A textured frame so det.crop(frame) yields a usable crop.
    return _RNG.integers(0, 256, size=(FRAME_H, FRAME_W, 3), dtype=np.uint8)


def test_follower_lock_and_reach():
    print("\n[follower] lock in scanner region, follow, reach cart")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()

    xs = _transit_xs()
    # Frame 0: one item in the scanner region -> lock, TRACKING.
    st = f.update([_det(xs[0])], frame, _meta(0))
    check("locks single scanner-region item", st == FollowStatus.TRACKING, st)

    # Frames 1..n-1: item moves rightward in small steps, still tracking until
    # the last, where its centroid crosses into the cart-entry region.
    st = None
    for i, x in enumerate(xs[1:], start=1):
        st = f.update([_det(x)], frame, _meta(i))
    check("reaches cart region", st == FollowStatus.REACHED_CART, st)
    check("reached_cart flag set", f.reached_cart, str(f.reached_cart))
    check("kept usable crops across path", f.usable_crop_count >= 3,
          str(f.usable_crop_count))


def test_follower_waits_when_scanner_crowded():
    print("\n[follower] two items in scanner region -> no guess (WAITING)")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()
    st = f.update([_det(30), _det(90, y=300)], frame, _meta(0))
    check("does not lock when 2 contest scanner", st == FollowStatus.WAITING, st)
    check("nothing locked yet", f.target_bbox is None, str(f.target_bbox))


def test_follower_ambiguous():
    print("\n[follower] two equally-good matches mid-follow -> AMBIGUOUS")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()
    f.update([_det(SCANNER_X)], frame, _meta(0))          # lock at x=40
    # Two detections placed symmetrically around the target (centroid x=80):
    # equal centroid distance and equal IoU -> equal association score, well
    # inside the ambiguity margin -> cannot tell which one IS the target.
    st = f.update([_det(20), _det(60)], frame, _meta(1))
    check("flags AMBIGUOUS on contested match",
          st == FollowStatus.AMBIGUOUS, st)
    check("AMBIGUOUS is a BROKEN status",
          st in FollowStatus.BROKEN, st)


def test_follower_merged():
    print("\n[follower] blob balloons (item+hand fuse) -> MERGED")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()
    f.update([_det(SCANNER_X, w=80, h=80)], frame, _meta(0))   # baseline area 6400
    # Next frame the matched blob is far bigger than baseline*MERGE_AREA_RATIO.
    big = int(80 * (MERGE_AREA_RATIO + 0.5) ** 0.5) + 40
    st = f.update([_det(90, w=big, h=big)], frame, _meta(1))
    check("flags MERGED on ballooning blob", st == FollowStatus.MERGED, st)
    check("MERGED is a BROKEN status", st in FollowStatus.BROKEN, st)


def test_follower_lost():
    print("\n[follower] target disappears past grace -> LOST")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()
    f.update([_det(SCANNER_X)], frame, _meta(0))   # lock
    st = None
    # No acceptable detection for more than the grace window.
    for i in range(1, VERIFY_LOST_GRACE_FRAMES + 3):
        st = f.update([], frame, _meta(i))
    check("flags LOST after grace window", st == FollowStatus.LOST, st)
    check("LOST is a BROKEN status", st in FollowStatus.BROKEN, st)


def test_follower_seq_dedupe():
    print("\n[follower] re-reading one frame (same seq) adds no second crop")
    f = ItemFollower((FRAME_W, FRAME_H))
    frame = _frame()
    f.update([_det(SCANNER_X)], frame, _meta(0))
    n_after_lock = f.usable_crop_count
    # Same seq again: must be ignored entirely (no new crop, status unchanged).
    st = f.update([_det(SCANNER_X)], frame, _meta(0))
    check("same seq keeps crop count", f.usable_crop_count == n_after_lock,
          f"{f.usable_crop_count} vs {n_after_lock}")
    check("same seq does not change status", st == FollowStatus.TRACKING, st)
    # A NEW seq for a slightly-moved detection (within association range) adds
    # one more crop.
    f.update([_det(SCANNER_X + _STEP)], frame, _meta(1))
    check("new seq adds a crop", f.usable_crop_count == n_after_lock + 1,
          str(f.usable_crop_count))


# ═════════════════════════════════════════════════════════════════
# CUSTODY: gating (both proofs), second-scan abort, broken-follow RETRY
# ═════════════════════════════════════════════════════════════════

def test_custody_gating_and_flow():
    print("\n[custody] both proofs required; second scan aborts; broken -> RETRY")
    from ml.custody import CustodyController
    from ml.detector import OracleDetector
    from ml.events import MockBarcodeSource, MockWeightSource

    frame = _frame()

    def build(app, col):
        det = OracleDetector()
        barcode = MockBarcodeSource(["sku_a"])
        weight = MockWeightSource()
        verifier = _make_verifier(app, col)
        ctrl = CustodyController(det, verifier, barcode, weight,
                                 frame_size=(FRAME_W, FRAME_H))
        return det, barcode, weight, ctrl

    hi_app = VERIFY_APPEARANCE_THRESHOLD + 0.1
    hi_col = VERIFY_COLOR_THRESHOLD + 0.1

    xs = _transit_xs()

    # --- reached cart but NO weight settle -> no verdict yet ---
    det, barcode, weight, ctrl = build(hi_app, hi_col)
    barcode.scan("sku_a")
    seq = 0
    r = None
    for x in xs:                        # smooth transit into the cart region
        det.set([_det(x)]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("reached cart, no weight -> withholds verdict", r is None, str(r))
    check("follower reached cart", ctrl.reached_cart, str(ctrl.reached_cart))

    # --- now the weight changes then settles (events arrive over frames) ---
    # The mock emits CHANGING first, SETTLED next; custody polls one event per
    # frame, exactly as the Arduino serial driver will feed them.
    weight.begin_change()
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("reached cart + only CHANGING seen -> still withholds", r is None, str(r))
    weight.settle(250.0)
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("both proofs in -> verdict produced", r is not None, str(r))
    check("clean transit + good scores -> MATCH",
          r is not None and r.verdict == Verdict.MATCH,
          r.verdict if r else "None")

    # --- weight fully settles but item never reaches cart -> no verdict ---
    # Proves the SPATIAL gate is doing the withholding: both weight events are
    # consumed (weight_settled becomes True) yet the item stays left of cart.
    det, barcode, weight, ctrl = build(hi_app, hi_col)
    barcode.scan("sku_a")
    det.set([_det(SCANNER_X)]); ctrl.process(frame, _meta(100))
    weight.begin_change()
    det.set([_det(SCANNER_X + _STEP)]); ctrl.process(frame, _meta(101))
    weight.settle(250.0)
    det.set([_det(SCANNER_X + _STEP)]); r = ctrl.process(frame, _meta(102))
    check("weight settled but not reached cart -> withholds verdict",
          r is None, str(r))
    check("weight_settled true, reached_cart false",
          ctrl.weight_settled and not ctrl.reached_cart,
          f"settled={ctrl.weight_settled} reached={ctrl.reached_cart}")

    # --- second scan while open aborts the first as RETRY ---
    det, barcode, weight, ctrl = build(hi_app, hi_col)
    barcode.scan("sku_a")
    det.set([_det(SCANNER_X)]); ctrl.process(frame, _meta(200))
    barcode.scan("sku_a")               # a new scan arrives mid-transaction
    det.set([_det(SCANNER_X + _STEP)]); r = ctrl.process(frame, _meta(201))
    check("second scan aborts open txn as RETRY",
          r is not None and r.verdict == Verdict.RETRY,
          r.verdict if r else "None")

    # --- broken follow (ambiguous) resolves RETRY ---
    det, barcode, weight, ctrl = build(hi_app, hi_col)
    barcode.scan("sku_a")
    det.set([_det(SCANNER_X)]); ctrl.process(frame, _meta(300))
    det.set([_det(20), _det(60)]); r = ctrl.process(frame, _meta(301))
    check("broken follow -> RETRY",
          r is not None and r.verdict == Verdict.RETRY,
          r.verdict if r else "None")


# ═════════════════════════════════════════════════════════════════
# JOINT PASS: appearance AND colour must agree on the SAME crop
# ═════════════════════════════════════════════════════════════════

class SeqRecognizer:
    """
    A recognizer whose appearance similarity is a DIFFERENT scripted number
    per crop (in crop order), so we can drive individual crops above/below the
    threshold independently — impossible with the fixed-score StubRecognizer.
    """

    def __init__(self, scores) -> None:
        self.scores = list(scores)
        self.i = 0

    def embed(self, crop):
        return np.zeros(4, dtype=np.float32)

    def similarity(self, a, b):
        # verify() calls this exactly once per crop (one appearance ref), so
        # the counter tracks the crop index.
        s = self.scores[self.i % len(self.scores)]
        self.i += 1
        return s


def _make_scripted_verifier(app_scores, col_scores, sku: str = "sku_a"):
    """
    Build a verifier whose appearance AND colour scores are scripted per crop,
    aligned to crop order, so a specific pattern of per-crop passes can be
    constructed (e.g. appearance and colour passing on DIFFERENT crops).
    """
    recog = SeqRecognizer(app_scores)
    appearance_db = {sku: [np.zeros(4, dtype=np.float32)]}
    # Colour ref of [1.0]; a per-crop colour_hist_fn returns [score_i], so
    # best_similarity == score_i for crop i.
    colour_db = {sku: ColourReference([np.array([1.0], dtype=np.float32)])}
    state = {"i": 0}

    def colour_hist_fn(crop):
        v = col_scores[state["i"] % len(col_scores)]
        state["i"] += 1
        return np.array([v], dtype=np.float32)

    return ProductVerifier(recog, appearance_db=appearance_db,
                           colour_db=colour_db, colour_hist_fn=colour_hist_fn)


def test_verifier_joint_pass_required():
    print("\n[verifier] MATCH needs BOTH channels on the SAME crop (anti-swap)")
    hi_app = VERIFY_APPEARANCE_THRESHOLD + 0.1
    lo_app = VERIFY_APPEARANCE_THRESHOLD - 0.2
    hi_col = VERIFY_COLOR_THRESHOLD + 0.1
    lo_col = VERIFY_COLOR_THRESHOLD - 0.2
    crops = [_usable_crop() for _ in range(4)]

    # ANTI-CORRELATED: appearance passes on crops 0,1; colour passes on 2,3.
    # Each channel clears 50% on its own — the OLD separate-fraction logic
    # would have called this MATCH — but NO single crop passes both, which is
    # exactly the evidence a same-weight swap can fake.  Must NOT be MATCH.
    app = [hi_app, hi_app, lo_app, lo_app]
    col = [lo_col, lo_col, hi_col, hi_col]
    r = _make_scripted_verifier(app, col).verify("sku_a", crops)
    check("anti-correlated passes -> NOT MATCH",
          r.verdict != Verdict.MATCH, r.verdict)
    check("anti-correlated -> SUSPECT (appearance carried, colour didn't)",
          r.verdict == Verdict.SUSPECT, r.verdict)
    check("no crop passed both -> joint_pass_frac == 0",
          r.joint_pass_frac == 0.0, str(r.joint_pass_frac))
    check("but each channel DID clear 50% separately (the trap)",
          r.appearance_pass_frac == 0.5 and r.colour_pass_frac == 0.5,
          f"app={r.appearance_pass_frac} col={r.colour_pass_frac}")
    check("anti-correlated result is not accepted", not r.accepted,
          str(r.accepted))

    # CORRELATED: both channels pass together on crops 0,1,2 (colour varies
    # per crop, proving per-crop scoring is real) -> joint fraction high.
    app = [hi_app, hi_app + 0.05, hi_app + 0.02, lo_app]
    col = [hi_col, hi_col, hi_col, hi_col]
    r = _make_scripted_verifier(app, col).verify("sku_a", crops)
    joint_expected = 3 / 4  # crops 0,1,2 pass both
    check("jointly-passing crops -> MATCH",
          r.verdict == Verdict.MATCH and joint_expected >= VERIFY_PASS_FRACTION,
          f"{r.verdict} joint={r.joint_pass_frac}")


# ═════════════════════════════════════════════════════════════════
# ONLY MATCH ACCEPTS  (UNAVAILABLE / MISMATCH / SUSPECT / RETRY block)
# ═════════════════════════════════════════════════════════════════

def test_only_match_accepts():
    print("\n[verifier] only MATCH accepts; UNAVAILABLE & others block")
    crops = [_usable_crop() for _ in range(VERIFY_MIN_USABLE_FRAMES + 1)]
    hi_app = VERIFY_APPEARANCE_THRESHOLD + 0.1
    hi_col = VERIFY_COLOR_THRESHOLD + 0.1
    lo = VERIFY_APPEARANCE_THRESHOLD - 0.2
    lo_col = VERIFY_COLOR_THRESHOLD - 0.2

    cases = [
        ("UNAVAILABLE", _make_verifier(hi_app, hi_col).verify("nope", crops)),
        ("MISMATCH", _make_verifier(lo, lo_col).verify("sku_a", crops)),
        ("SUSPECT", _make_verifier(hi_app, lo_col).verify("sku_a", crops)),
        ("RETRY", _make_verifier(hi_app, hi_col).verify("sku_a", crops,
                                                        follower_broken=True)),
    ]
    for label, r in cases:
        check(f"{label} does not accept (never weight-only pass)",
              not r.accepted, f"{r.verdict} accepted={r.accepted}")
    r = _make_verifier(hi_app, hi_col).verify("sku_a", crops)
    check("MATCH accepts", r.accepted, r.verdict)


# ═════════════════════════════════════════════════════════════════
# COLOUR: white / low-saturation packaging is represented (format v2)
# ═════════════════════════════════════════════════════════════════

def _solid_bgr(b, g, r, size: int = 64, noise: int = 4) -> np.ndarray:
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[:, :, 0] = b
    img[:, :, 1] = g
    img[:, :, 2] = r
    if noise:
        jitter = _RNG.integers(-noise, noise + 1, img.shape)
        img = np.clip(img.astype(int) + jitter, 0, 255).astype(np.uint8)
    return img


def test_colour_low_saturation():
    print("\n[verifier] white/low-saturation packaging gets a real fingerprint")
    white1 = _solid_bgr(235, 235, 235)   # near-white, unsaturated
    white2 = _solid_bgr(228, 230, 233)   # another near-white
    blue = _solid_bgr(200, 60, 60)       # strongly saturated (BGR blue)

    # v1 would have produced an all-zero vector for an unsaturated crop; v2
    # must not — a white box now has a non-zero colour fingerprint.
    n_white = float(np.linalg.norm(colour_hist(white1)))
    check("white crop -> non-zero colour fingerprint (v2)", n_white > 0.0,
          f"norm={n_white:.3f}")

    ref = ColourReference([colour_hist(white1)])
    s_white = ref.best_similarity(colour_hist(white2))
    s_blue = ref.best_similarity(colour_hist(blue))
    check("white matches white (>= colour threshold)",
          s_white >= VERIFY_COLOR_THRESHOLD, f"{s_white:.3f}")
    check("coloured swap fails against a white reference",
          s_blue < VERIFY_COLOR_THRESHOLD, f"{s_blue:.3f}")


# ═════════════════════════════════════════════════════════════════
# PRODUCT CROP: shared cropper resolves / refuses deterministically
# ═════════════════════════════════════════════════════════════════

def test_product_crop():
    print("\n[crop] crop_product resolves one product and refuses ambiguity")
    from ml.product_crop import CropStatus, crop_product

    H, W = 480, 640

    def canvas():
        return np.full((H, W, 3), 127, dtype=np.uint8)

    def put_square(img, x, y, s, val=240):
        # A solid contrasting square: its edges carry strong gradient, so the
        # cropper sees one product-shaped region.
        img[y:y + s, x:x + s] = val

    # Blank frame -> EMPTY (no product-like texture).
    r = crop_product(canvas())
    check("blank frame -> EMPTY", r.status == CropStatus.EMPTY, r.status)

    # One clear product filling enough of the frame -> OK with a crop.
    img = canvas(); put_square(img, 200, 130, 240)
    r = crop_product(img)
    check("single clear product -> OK", r.status == CropStatus.OK,
          f"{r.status} ({r.reason})")
    check("OK yields a non-empty crop",
          r.ok and r.crop is not None and r.crop.size > 0, "no crop")

    # A product that fills too little of the frame -> TOO_SMALL.
    img = canvas(); put_square(img, 300, 220, 80)
    r = crop_product(img)
    check("far-away product -> TOO_SMALL", r.status == CropStatus.TOO_SMALL,
          f"{r.status} (area {r.area_frac:.3f})")

    # Two comparable regions -> AMBIGUOUS (refuse to guess which is THE item).
    img = canvas(); put_square(img, 60, 150, 170); put_square(img, 410, 150, 170)
    r = crop_product(img)
    check("two comparable regions -> AMBIGUOUS",
          r.status == CropStatus.AMBIGUOUS, r.status)


# ═════════════════════════════════════════════════════════════════
# CUSTODY: transaction id on results; stale / mismatched weight dropped
# ═════════════════════════════════════════════════════════════════

def test_txn_id_and_weight_binding():
    print("\n[custody] txn id stamped on result; stale/mismatched weight dropped")
    from ml.custody import CustodyController
    from ml.detector import OracleDetector
    from ml.events import MockBarcodeSource, MockWeightSource

    frame = _frame()
    hi_app = VERIFY_APPEARANCE_THRESHOLD + 0.1
    hi_col = VERIFY_COLOR_THRESHOLD + 0.1
    xs = _transit_xs()

    def build():
        det = OracleDetector()
        barcode = MockBarcodeSource()
        weight = MockWeightSource()
        verifier = _make_verifier(hi_app, hi_col)
        ctrl = CustodyController(det, verifier, barcode, weight,
                                 frame_size=(FRAME_W, FRAME_H))
        return det, barcode, weight, ctrl

    def transit(det, ctrl, start_seq):
        seq = start_seq
        for x in xs:
            det.set([_det(x)]); ctrl.process(frame, _meta(seq)); seq += 1
        return seq

    # (a) a backend-provided txn id flows onto the result; weight_delta surfaced
    det, barcode, weight, ctrl = build()
    barcode.scan("sku_a", txn_id="T-100")
    seq = transit(det, ctrl, 0)
    weight.begin_change()
    det.set([_det(xs[-1])]); ctrl.process(frame, _meta(seq)); seq += 1
    weight.settle(250.0, txn_id="T-100")
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("result carries the backend txn id",
          r is not None and r.txn_id == "T-100", r.txn_id if r else "None")
    check("result surfaces the settled weight delta",
          r is not None and abs(r.weight_delta - 250.0) < 1e-6,
          str(r.weight_delta if r else None))
    check("all proofs + good scores -> MATCH",
          r is not None and r.verdict == Verdict.MATCH,
          r.verdict if r else "None")

    # (b) a settle tagged for a DIFFERENT txn must NOT complete this one
    det, barcode, weight, ctrl = build()
    barcode.scan("sku_a", txn_id="T-200")
    seq = transit(det, ctrl, 400)
    weight.begin_change()
    det.set([_det(xs[-1])]); ctrl.process(frame, _meta(seq)); seq += 1
    weight.settle(250.0, txn_id="WRONG")
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("mismatched-txn settle is dropped (no verdict)", r is None, str(r))
    check("mismatched settle does not bind weight",
          not ctrl.weight_settled, str(ctrl.weight_settled))
    weight.settle(250.0, txn_id="T-200")   # the correct one now completes it
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("correct-txn settle completes the transaction",
          r is not None and r.verdict == Verdict.MATCH,
          r.verdict if r else "None")

    # (c) a stale settle (time-stamped before this scan opened) is dropped
    det, barcode, weight, ctrl = build()
    barcode.scan("sku_a", txn_id="T-300")
    seq = transit(det, ctrl, 500)
    weight.begin_change()
    det.set([_det(xs[-1])]); ctrl.process(frame, _meta(seq)); seq += 1
    weight.settle(250.0, txn_id="T-300", ts=0.0)   # ts=0 predates started_ts
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("stale settle (old timestamp) is dropped",
          r is None and not ctrl.weight_settled,
          f"r={r} settled={ctrl.weight_settled}")


def main():
    print("=" * 60)
    print("  NXTCart-Cam — headless verification branch coverage")
    print("  (logic only; no camera, no model, no reference photos)")
    print("=" * 60)

    test_verifier_truth_table()
    test_verifier_joint_pass_required()
    test_only_match_accepts()
    test_colour_low_saturation()
    test_product_crop()
    test_follower_lock_and_reach()
    test_follower_waits_when_scanner_crowded()
    test_follower_ambiguous()
    test_follower_merged()
    test_follower_lost()
    test_follower_seq_dedupe()
    test_custody_gating_and_flow()
    test_txn_id_and_weight_binding()

    print("\n" + "=" * 60)
    if _failures:
        print(f"  {len(_failures)} CHECK(S) FAILED: {_failures}")
        print("=" * 60)
        sys.exit(1)
    print("  ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
