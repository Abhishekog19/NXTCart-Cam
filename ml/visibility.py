# ---------------------------------------------------------------
# ml/visibility.py  --  "IS THERE ENOUGH PRODUCT HERE TO JUDGE?"
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The verifier must never score a crop that does not actually contain a
# clear view of a product — a hand, a motion-blurred smear, a blank patch
# of table, or a sliver of a half-occluded item all produce CONFIDENT
# NONSENSE if you push them through an embedding.  So every crop is gated
# by ONE shared "is this usable?" test before anyone scores it.
#
# THE TRAP THIS AVOIDS
# ─────────────────────
# The obvious visibility test is "how many saturated, colourful pixels are
# there?" — that is what ml/recognizer.ColorCodeRecognizer uses to ignore a
# grey background.  But a great many real products are LOW SATURATION: a
# white rice bag, a beige carton, a clear bottle.  Judging visibility by
# colour alone would call those products invisible and every transaction
# involving them would wrongly resolve RETRY.
#
# So visibility here is decided by CONTENT, not COLOUR.  A real product,
# whatever its colour, has TEXTURE and EDGES — printing, seams, lettering,
# a silhouette against the surface.  A hand or a blank patch does not.  We
# measure that colour-independently (grayscale standard deviation + edge /
# Laplacian energy).  Colourfulness, if present, only adds confidence; its
# absence never condemns a crop.
# ---------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ml.config import VIS_EDGE_MIN, VIS_MIN_CROP_PX, VIS_TEXTURE_MIN


@dataclass
class Visibility:
    """
    The outcome of the usable-view test for one crop.

    Attributes
    ----------
    usable : bool
        True when the crop is worth scoring.  This is the only field callers
        normally branch on.
    reason : str
        Short human-readable explanation (for the UI / logs / tests), e.g.
        "ok", "too small", "flat/blurred".
    texture : float
        Grayscale standard deviation actually measured (for display bars).
    edges : float
        Laplacian energy actually measured.
    """
    usable: bool
    reason: str
    texture: float = 0.0
    edges: float = 0.0


def assess(crop: np.ndarray) -> Visibility:
    """
    Decide whether a crop contains enough of a product to be scored.

    The cues are combined so that NO SINGLE colour-based signal can veto a
    real (possibly low-saturation) product:

      1. Size floor      — too few pixels to judge anything.
      2. Texture (std)   — a flat patch (hand, blank table, heavy blur) has
                           low grayscale variance; a printed package does not.
      3. Edge energy     — a product has contours/lettering; a smear does not.

    A crop passes when it clears the size floor AND clears EITHER the texture
    OR the edge cue (either is sufficient evidence of real content — some
    products are smooth but high-contrast against the surface, others are
    matte but finely textured).
    """
    if crop is None or crop.size == 0:
        return Visibility(False, "empty")

    h, w = crop.shape[:2]
    if min(h, w) < VIS_MIN_CROP_PX:
        return Visibility(False, "too small")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop

    texture = float(np.std(gray))
    # Laplacian variance is the standard "focus / detail" measure: high for a
    # sharp, detailed patch, low for a blurred or blank one.
    edges = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Normalise edge energy into roughly the same magnitude as VIS_EDGE_MIN by
    # taking a square root — Laplacian variance grows quadratically with
    # contrast, and the raw numbers are otherwise unintuitive to tune.
    edges_scaled = float(np.sqrt(edges))

    has_texture = texture >= VIS_TEXTURE_MIN
    has_edges = edges_scaled >= VIS_EDGE_MIN

    if has_texture or has_edges:
        return Visibility(True, "ok", texture, edges_scaled)
    return Visibility(False, "flat/blurred", texture, edges_scaled)


def is_usable(crop: np.ndarray) -> bool:
    """Convenience boolean wrapper around assess()."""
    return assess(crop).usable
