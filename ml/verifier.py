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
#   appearance pass & colour pass -> MATCH       accept
#   appearance pass & colour fail -> SUSPECT     flag (right shape, wrong
#                                                 colour: the swap attack)
#   appearance fail & colour pass -> MISMATCH    colour ALONE never accepts
#   appearance fail & colour fail -> MISMATCH
#   too few usable crops / broken -> RETRY       ask the shopper to redo
#   SKU not in the database       -> UNAVAILABLE cannot judge, do not accept
#
# MULTI-VIEW SMOOTHING
# ─────────────────────
# A channel "passes overall" when at least VERIFY_PASS_FRACTION of the
# usable crops pass it.  One blurred frame cannot fail a good item, and one
# lucky frame cannot pass a wrong one — the decision rides on the weight of
# several independent views, which is the whole reason we followed the item
# across its journey instead of grabbing a single snapshot.
# ---------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

from ml.config import (
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
        app_scores: List[float] = []
        col_scores: List[float] = []
        for crop in usable:
            emb = self.recognizer.embed(crop)
            app_scores.append(max(
                (self.recognizer.similarity(emb, r) for r in refs),
                default=0.0))
            if colour_ref is not None:
                col_scores.append(colour_ref.best_similarity(
                    self._colour_hist_fn(crop)))
            else:
                col_scores.append(0.0)

        n = len(usable)
        app_pass_frac = sum(s >= VERIFY_APPEARANCE_THRESHOLD
                            for s in app_scores) / n
        col_pass_frac = sum(s >= VERIFY_COLOR_THRESHOLD
                            for s in col_scores) / n
        app_ok = app_pass_frac >= VERIFY_PASS_FRACTION
        col_ok = col_pass_frac >= VERIFY_PASS_FRACTION

        best_app = max(app_scores, default=0.0)
        best_col = max(col_scores, default=0.0)

        # ── the verdict table ───────────────────────────────────────
        if app_ok and col_ok:
            verdict, reason = Verdict.MATCH, (
                f"Appearance and colour both match '{expected_sku}'.")
        elif app_ok and not col_ok:
            verdict, reason = Verdict.SUSPECT, (
                f"Shape matches '{expected_sku}' but colour does not "
                f"(possible same-weight swap). Flagged for review.")
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
        )


# ── default colour histogram (identical to ColorCodeRecognizer.embed) ──
# Kept as a free function so the verifier does not depend on constructing a
# ColorCodeRecognizer, but uses the exact same computation, so a colour
# reference built at DB time and a live crop are measured the same way.
_H_BINS = 18
_S_BINS = 4


def _default_colour_hist(crop: np.ndarray, sat_min: int = 90,
                         val_min: int = 60) -> np.ndarray:
    import cv2
    if crop is None or crop.size == 0:
        return np.zeros(_H_BINS * _S_BINS, dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    mask = ((s >= sat_min) & (v >= val_min)).astype(np.uint8) * 255
    if int(np.count_nonzero(mask)) == 0:
        return np.zeros(_H_BINS * _S_BINS, dtype=np.float32)
    hist = cv2.calcHist([hsv], [0, 1], mask, [_H_BINS, _S_BINS],
                        [0, 180, 0, 256]).flatten().astype(np.float32)
    nrm = float(np.linalg.norm(hist))
    return hist / nrm if nrm > 0 else hist


def colour_hist(crop: np.ndarray) -> np.ndarray:
    """Public alias so build_db.py can build colour references identically."""
    return _default_colour_hist(crop)


def load_colour_db(path: Optional[str] = None) -> dict:
    """
    Load the per-SKU colour references written by build_db.py into
    {sku: ColourReference}.

    Returns an EMPTY dict (never raises) when the database is missing or was
    built before the colour block existed — the verifier then treats every
    SKU as having no colour reference, which can only make it MORE cautious
    (MATCH becomes unreachable, SUSPECT at best), never less.  That is the
    safe direction, and it keeps the demo starting gracefully with no data.
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
    colours = raw.get("colours") or {}
    out: dict = {}
    for sku, hists in colours.items():
        out[sku] = ColourReference(hists or [])
    return out
