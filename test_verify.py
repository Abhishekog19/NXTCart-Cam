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
)
from ml.detector import Detection
from ml.frame_source import FrameMeta
from ml.item_follower import FollowStatus, ItemFollower
from ml.verifier import ColourReference, ProductVerifier, Verdict

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

    # --- now the weight settles -> MATCH is produced ---
    weight.begin_change(); weight.settle(250.0)
    det.set([_det(xs[-1])]); r = ctrl.process(frame, _meta(seq)); seq += 1
    check("both proofs in -> verdict produced", r is not None, str(r))
    check("clean transit + good scores -> MATCH",
          r is not None and r.verdict == Verdict.MATCH,
          r.verdict if r else "None")

    # --- weight settles but item never reaches cart -> no verdict ---
    det, barcode, weight, ctrl = build(hi_app, hi_col)
    barcode.scan("sku_a")
    det.set([_det(SCANNER_X)]); ctrl.process(frame, _meta(100))
    weight.begin_change(); weight.settle(250.0)
    det.set([_det(SCANNER_X + _STEP)]); r = ctrl.process(frame, _meta(101))
    check("weight but not reached cart -> withholds verdict", r is None, str(r))

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


def main():
    print("=" * 60)
    print("  NXTCart-Cam — headless verification branch coverage")
    print("  (logic only; no camera, no model, no reference photos)")
    print("=" * 60)

    test_verifier_truth_table()
    test_follower_lock_and_reach()
    test_follower_waits_when_scanner_crowded()
    test_follower_ambiguous()
    test_follower_merged()
    test_follower_lost()
    test_follower_seq_dedupe()
    test_custody_gating_and_flow()

    print("\n" + "=" * 60)
    if _failures:
        print(f"  {len(_failures)} CHECK(S) FAILED: {_failures}")
        print("=" * 60)
        sys.exit(1)
    print("  ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
