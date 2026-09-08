# ---------------------------------------------------------------
# ml/verifier.py  --  IS THE ENTERED ITEM THE SCANNED SKU?  (1-vs-1)
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The barcode already told us WHICH product this is supposed to be.  So the
# camera is not asked the hard open-set question "what is this?" — it is
# asked the easy, reliable one:
#
#       "The scanner says SKU X.  Do these crops of the item that just
#        travelled into the cart actually look like X — yes / no / unsure?"
#
# TWO INDEPENDENT CHANNELS, ABSOLUTE THRESHOLDS
# ───────────────────────────────────────────────
# With only the expected SKU to compare against, "which product ranks #1?"
# is meaningless — X always ranks #1 in a field of one.  So we do NOT use
# the matcher's rank/`confident` machinery here.  We test two RAW scores
# against ABSOLUTE thresholds, on the SAME crops:
#
#   appearance : cosine similarity of the crop's MobileNet embedding to the
#                SKU's appearance references (the real recognition channel).
#   colour     : histogram similarity of the crop's colour to the SKU's
#                colour references (a coarse channel whose ONE job is to
#                catch the attack weight cannot — a same-weight item of a
#                different colour swapped in for the scanned one).
#
# THE VERDICT TABLE  (no branch defaults to acceptance)
# ──────────────────────────────────────────────────────
# A crop passes JOINTLY when appearance AND colour both pass on THAT SAME
# crop.  MATCH requires enough jointly-passing crops; the weaker outcomes key
# off appearance alone.
#
#   enough crops pass BOTH (jointly) -> MATCH       accept
#   appearance passes, not enough
#     jointly                        -> SUSPECT     flag (right shape, colour
#                                                    didn't co-occur: the swap)
#   appearance does not pass overall -> MISMATCH    colour ALONE never accepts
#   too few usable crops / broken    -> RETRY       ask the shopper to redo
#   SKU not in the database          -> UNAVAILABLE cannot judge, do not accept
#
# WHY JOINT, NOT SEPARATE  (this is a real defense, not bookkeeping)
# ───────────────────────────────────────────────────────────────────
# If appearance and colour were smoothed SEPARATELY — "≥ fraction of crops
# pass appearance" and, independently, "≥ fraction pass colour" — an item
# could be accepted when NO single crop ever passed both at once: the front
# frames carry the right shape, some later blurry frames happen to clear the
# coarse colour bar, and the two fractions each cross the line on disjoint
# crops.  That is exactly the evidence a same-weight swap can manufacture.
# So MATCH is gated on the fraction of crops that pass appearance AND colour
# TOGETHER (VERIFY_PASS_FRACTION of them).  One blurred frame still cannot
# fail a good item and one lucky frame cannot pass a wrong one, but the two
# channels must now agree on the SAME views, not merely in aggregate.
# ---------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

from ml.config import (
    COLOUR_ACH_VAL_MIN,
    COLOUR_FORMAT_VERSION,
    COLOUR_SAT_MIN,
    COLOUR_VAL_MIN,
    VERIFY_APPEARANCE_THRESHOLD,
    VERIFY_COLOR_THRESHOLD,
    VERIFY_MIN_USABLE_FRAMES,
    VERIFY_PASS_FRACTION,
)
from ml.visibility import assess


class Verdict:
    """The possible outcomes of a verification (strings for logs/UI)."""
    MATCH       = "MATCH"        # accept: appearance AND colour agree
    SUSPECT     = "SUSPECT"      # appearance ok, colour wrong -> swap attack
    MISMATCH    = "MISMATCH"     # appearance fails -> not the scanned item
    RETRY       = "RETRY"        # not enough clean evidence -> redo it
    UNAVAILABLE = "UNAVAILABLE"  # no reference data for this SKU -> can't judge

    # The ONLY verdict that lets an item through unflagged.
    ACCEPTING = {MATCH}


@dataclass
class VerdictResult:
    """
    The full outcome of one verification, structured so the UI, the logs,
    and the fusion layer can all act on it and explain it.
    """
    verdict: str
    appearance_score: float          # best per-crop appearance score seen
    colour_score: float              # best per-crop colour score seen
    appearance_pass_frac: float      # fraction of crops passing appearance
    colour_pass_frac: float          # fraction of crops passing colour
    usable_crops: int
    reason: str
    expected_sku: str = ""
    # fraction of crops passing appearance AND colour on the SAME crop; this
    # (not the two separate fractions) is what MATCH is gated on.
    joint_pass_frac: float = 0.0
    # Transaction identity, stamped by the custody controller so every camera
    # result can be tied to the scan that produced it (and rejected by the
    # backend if it arrives against the wrong transaction).
    txn_id: str = ""
    # The settled weight change (grams) bound to this transaction, surfaced so
    # the backend can run its own expected-weight-for-SKU check.  0.0 when no
    # weight event was bound.
    weight_delta: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.verdict in Verdict.ACCEPTING


class ColourReference:
    """
    A SKU's colour fingerprint: one histogram per reference photo (multiple
    per SKU, paired to the same photos that produced the appearance refs).

    The histogram and its comparison are the SAME as
    ml.recognizer.ColorCodeRecognizer, so references and live crops are
    measured identically — a live crop is scored against its BEST-matching
    colour reference (best-angle, mirroring the appearance channel).
    """

    def __init__(self, histograms: List[np.ndarray]) -> None:
        self.histograms = [h for h in histograms if h is not None and h.size]

    def best_similarity(self, crop_hist: np.ndarray) -> float:
        if crop_hist is None or crop_hist.size == 0 or not self.histograms:
            return 0.0
        return max(float(np.dot(crop_hist, h)) for h in self.histograms)


class ProductVerifier:
    """
    Verifies that collected crops match ONE expected SKU.

    Parameters
    ----------
    recognizer : Recognizer
        Provides embed(crop) -> appearance vector and similarity(a, b).  In
        production this is EmbeddingRecognizer (MobileNet); in tests it can be
        any object honouring the same protocol.
    appearance_db : dict {sku: [embedding, ...]}
        Appearance references per SKU (the product mapping build_db.py saves).
    colour_db : dict {sku: ColourReference}, optional
        Colour references per SKU.  If a SKU has no colour reference the
        colour channel cannot pass, so such a SKU can never reach MATCH — it
        will resolve SUSPECT at best, which is the safe direction.
    colour_hist_fn : callable crop -> histogram, optional
        How to turn a live crop into a colour histogram.  Defaults to the
        ColorCodeRecognizer method so live and reference colour use one code
        path.
    """

    def __init__(
        self,
        recognizer,
        appearance_db: Optional[dict] = None,
        colour_db: Optional[dict] = None,
        colour_hist_fn: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    ) -> None:
        self.recognizer = recognizer
        self.appearance_db = appearance_db or {}
        self.colour_db = colour_db or {}
        self._colour_hist_fn = colour_hist_fn or _default_colour_hist

    def verify(self, expected_sku: str, crops: List[np.ndarray],
               follower_broken: bool = False) -> VerdictResult:
        """
        Judge whether `crops` show `expected_sku`.

        follower_broken=True forces RETRY: the chain of custody was broken
        (ambiguous / merged / lost), so however good a stray crop looks we
        cannot attribute it to the scanned item.
        """
        # ── no reference data -> cannot judge, must not accept ───────
        refs = self.appearance_db.get(expected_sku)
        if not refs:
            return VerdictResult(
                Verdict.UNAVAILABLE, 0.0, 0.0, 0.0, 0.0, 0,
                f"No reference data for '{expected_sku}'. Cannot verify.",
                expected_sku)

        # ── broken custody -> RETRY regardless of crop content ───────
        if follower_broken:
            return VerdictResult(
                Verdict.RETRY, 0.0, 0.0, 0.0, 0.0, len(crops or []),
                "Lost track of the item during handling. Please re-scan.",
                expected_sku)

        # ── keep only genuinely usable crops ─────────────────────────
        usable = [c for c in (crops or []) if assess(c).usable]
        if len(usable) < VERIFY_MIN_USABLE_FRAMES:
            return VerdictResult(
                Verdict.RETRY, 0.0, 0.0, 0.0, 0.0, len(usable),
                f"Only {len(usable)} clear view(s) of the item "
                f"(need {VERIFY_MIN_USABLE_FRAMES}). Please re-present it.",
                expected_sku)

        colour_ref: Optional[ColourReference] = self.colour_db.get(expected_sku)

        # ── score every usable crop on both channels ────────────────
        # Track per-crop PASS booleans (not just the aggregate counts) so we
        # can require the two channels to agree on the SAME crop.
        app_scores: List[float] = []
        col_scores: List[float] = []
        app_pass: List[bool] = []
        col_pass: List[bool] = []
        joint_pass: List[bool] = []
        for crop in usable:
            emb = self.recognizer.embed(crop)
            a = max((self.recognizer.similarity(emb, r) for r in refs),
                    default=0.0)
            if colour_ref is not None:
                c = colour_ref.best_similarity(self._colour_hist_fn(crop))
            else:
                c = 0.0
            app_scores.append(a)
            col_scores.append(c)
            ap = a >= VERIFY_APPEARANCE_THRESHOLD
            cp = c >= VERIFY_COLOR_THRESHOLD
            app_pass.append(ap)
            col_pass.append(cp)
            joint_pass.append(ap and cp)

        n = len(usable)
        app_pass_frac = sum(app_pass) / n
        col_pass_frac = sum(col_pass) / n
        joint_pass_frac = sum(joint_pass) / n
        # MATCH is gated on JOINT agreement (both channels on the same crop);
        # SUSPECT keys off appearance overall (right shape, colour didn't
        # co-occur enough — the same-weight swap looks like this).
        match_ok = joint_pass_frac >= VERIFY_PASS_FRACTION
        appearance_ok = app_pass_frac >= VERIFY_PASS_FRACTION

        best_app = max(app_scores, default=0.0)
        best_col = max(col_scores, default=0.0)

        # ── the verdict table ───────────────────────────────────────
        if match_ok:
            verdict, reason = Verdict.MATCH, (
                f"Appearance and colour both match '{expected_sku}' on the "
                f"same views.")
        elif appearance_ok:
            verdict, reason = Verdict.SUSPECT, (
                f"Shape matches '{expected_sku}' but colour did not agree on "
                f"the same views (possible same-weight swap). Flagged for "
                f"review.")
        else:
            verdict, reason = Verdict.MISMATCH, (
                f"Item does not match the scanned '{expected_sku}'.")

        return VerdictResult(
            verdict=verdict,
            appearance_score=round(best_app, 4),
            colour_score=round(best_col, 4),
            appearance_pass_frac=round(app_pass_frac, 3),
            colour_pass_frac=round(col_pass_frac, 3),
            usable_crops=n,
            reason=reason,
            expected_sku=expected_sku,
            joint_pass_frac=round(joint_pass_frac, 3),
        )


# ── default colour histogram (colour fingerprint format v2) ──────────
# Built as a free function (no ColorCodeRecognizer instance needed) so a
# colour reference built at DB time and a live crop are measured by the exact
# same code.  The vector has TWO parts, concatenated then L2-normalized:
#
#   1. CHROMATIC  : an H×S histogram over saturated, bright pixels — the hue
#                   fingerprint of a colourful product (unchanged from v1).
#   2. ACHROMATIC : a brightness histogram over the LOW-saturation pixels —
#                   this is the v2 addition.  A white / grey / beige product
#                   used to yield an all-zero vector (colour could never pass,
#                   MATCH unreachable); now it has a real "bright & colourless"
#                   fingerprint that matches other white boxes yet is still
#                   orthogonal to a coloured swap (whose mass lands in part 1).
#
# Because the length AND meaning differ from v1, the on-disk format is stamped
# COLOUR_FORMAT_VERSION and load_colour_db refuses a mismatched database.
_H_BINS = 18
_S_BINS = 4
_ACH_BINS = 8            # brightness bins for the achromatic (colourless) part
_COLOUR_DIM = _H_BINS * _S_BINS + _ACH_BINS


def _default_colour_hist(crop: np.ndarray) -> np.ndarray:
    import cv2
    if crop is None or crop.size == 0:
        return np.zeros(_COLOUR_DIM, dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    # Part 1 — chromatic H×S over pixels whose hue is real (saturated + bright).
    chroma_mask = ((s >= COLOUR_SAT_MIN) & (v >= COLOUR_VAL_MIN)) \
        .astype(np.uint8) * 255
    if int(np.count_nonzero(chroma_mask)) > 0:
        chroma = cv2.calcHist([hsv], [0, 1], chroma_mask, [_H_BINS, _S_BINS],
                              [0, 180, 0, 256]).flatten().astype(np.float32)
    else:
        chroma = np.zeros(_H_BINS * _S_BINS, dtype=np.float32)

    # Part 2 — brightness of the achromatic pixels (low saturation but not
    # near-black), so white vs grey vs dark packaging read differently.
    ach_mask = ((s < COLOUR_SAT_MIN) & (v >= COLOUR_ACH_VAL_MIN)) \
        .astype(np.uint8) * 255
    if int(np.count_nonzero(ach_mask)) > 0:
        ach = cv2.calcHist([v], [0], ach_mask, [_ACH_BINS], [0, 256]) \
            .flatten().astype(np.float32)
    else:
        ach = np.zeros(_ACH_BINS, dtype=np.float32)

    vec = np.concatenate([chroma, ach])
    nrm = float(np.linalg.norm(vec))
    return vec / nrm if nrm > 0 else vec


def colour_hist(crop: np.ndarray) -> np.ndarray:
    """Public alias so build_db.py can build colour references identically."""
    return _default_colour_hist(crop)


def load_colour_db(path: Optional[str] = None) -> dict:
    """
    Load the per-SKU colour references written by build_db.py into
    {sku: ColourReference}.

    Returns an EMPTY dict (never raises) when the database is missing, was
    built before the colour block existed, OR was built in an OLDER colour
    format.  A stale-format database is refused on purpose: a v1 vector has a
    different length and meaning than a v2 one, so scoring against it would be
    meaningless.  With colour disabled the verifier treats every SKU as having
    no colour reference, which can only make it MORE cautious (MATCH becomes
    unreachable, SUSPECT at best), never less — the safe direction — and it
    keeps the demo starting gracefully with no data.  A loud message tells you
    to rerun build_db.py.
    """
    import pickle
    from ml.config import DATABASE_PATH

    path = path or DATABASE_PATH
    try:
        with open(path, "rb") as f:
            raw = pickle.load(f)
    except (FileNotFoundError, OSError, pickle.UnpicklingError):
        return {}
    if not isinstance(raw, dict):
        return {}

    fmt = raw.get("colour_format")
    if fmt != COLOUR_FORMAT_VERSION:
        print(f"[verifier] Colour references are format {fmt!r}, but this "
              f"code needs v{COLOUR_FORMAT_VERSION}. Colour is DISABLED "
              f"(MATCH unreachable, SUSPECT at best) until you rerun "
              f"build_db.py.")
        return {}

    colours = raw.get("colours") or {}
    out: dict = {}
    for sku, hists in colours.items():
        out[sku] = ColourReference(hists or [])
    return out
