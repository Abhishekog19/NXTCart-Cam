# ---------------------------------------------------------------
# ml/recognizer.py  --  RECOGNIZER ABSTRACTION
#
# WHY THIS FILE EXISTS
# ─────────────────────
# You asked for the DETECTOR to be swappable so a trained model can drop
# in later.  The exact same principle is valuable for RECOGNITION, for two
# reasons:
#
#   1. It keeps the tracker from importing the heavy TFLite model directly,
#      so the identity / occlusion / cart logic can be unit-tested on a
#      machine with no model and no camera.
#
#   2. It gives us ONE place that owns "given a crop, who is this?" — which
#      is the operation we deliberately run rarely (only on good frames)
#      and then LOCK.
#
# The PRODUCTION recognizer (EmbeddingRecognizer) is a thin wrapper around
# your existing, unchanged modules:
#       embedding_extractor.extract_embedding  +  matcher.match
# Nothing about the real recognition path changes.
#
# The TEST recognizer (ColorCodeRecognizer) swaps ONLY the raw feature
# step (MobileNet embedding -> colour histogram) but still runs the SAME
# matcher.match() + the SAME SCORE_THRESHOLD / margin logic, so the test
# exercises the real decision code, not a reimplementation of it.
# ---------------------------------------------------------------

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from ml.matcher import EmbeddingDB, match


# ═════════════════════════════════════════════════════════════════
# THE INTERFACE
# ═════════════════════════════════════════════════════════════════

@runtime_checkable
class Recognizer(Protocol):
    """
    Anything that can turn a crop into (a) an appearance vector and
    (b) a match verdict, and compare two appearance vectors.

    analyze(crop)     -> (embedding, match_result_dict)
        The match_result_dict has the SAME shape matcher.match() returns:
        {top_name, top_score, margin, confident, rankings}.
        The tracker keeps the returned `embedding` so that, at lock time,
        it can store the exact vector that produced the winning verdict as
        the track's permanent identity_embedding.

    embed(crop)       -> embedding
        Just the appearance vector (used for the reacquire comparison and
        the appearance tie-breaker during association).

    similarity(a, b)  -> float in [-1, 1]
        Cosine similarity between two appearance vectors (both are
        L2-normalised, so this is a dot product).
    """

    def analyze(self, crop: np.ndarray) -> Tuple[np.ndarray, dict]: ...
    def embed(self, crop: np.ndarray) -> np.ndarray: ...
    def similarity(self, a: np.ndarray, b: np.ndarray) -> float: ...


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for already-L2-normalised vectors (a dot product)."""
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    return float(np.dot(a, b))


# ═════════════════════════════════════════════════════════════════
# PRODUCTION:  MobileNet embedding + your matcher (UNCHANGED)
# ═════════════════════════════════════════════════════════════════

class EmbeddingRecognizer:
    """
    The real recognizer used on the webcam.  A thin adapter over the
    existing pipeline — it deliberately adds no new logic.
    """

    def __init__(self, db: Optional[EmbeddingDB] = None) -> None:
        # Import here so that a machine with no TFLite runtime can still
        # import this module and use the test recognizer.
        from ml.embedding_extractor import extract_embedding
        from ml.matcher import load_database

        self._extract = extract_embedding
        self.db = db if db is not None else load_database()

    def embed(self, crop: np.ndarray) -> np.ndarray:
        return self._extract(crop)

    def analyze(self, crop: np.ndarray) -> Tuple[np.ndarray, dict]:
        emb = self._extract(crop)
        return emb, match(emb, db=self.db)

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return _cosine(a, b)


# ═════════════════════════════════════════════════════════════════
# TEST:  colour-code recognizer (content-based, deterministic)
# ═════════════════════════════════════════════════════════════════

class ColorCodeRecognizer:
    """
    A recognizer for headless testing.  Each product is represented by a
    distinct, saturated colour.  The appearance vector is a hue-saturation
    histogram computed ONLY over the "colourful" pixels of a crop (so the
    grey textured background is ignored).

    Why this is a faithful test tool, not a cheat:
      • It reads REAL pixels from the crop the detector produced.
      • It runs the REAL matcher.match() with the REAL thresholds.
      • It reproduces the ORIGINAL BUG's mechanism exactly: if an occluder
        covers most of a product, the crop's dominant colour changes, so a
        naive per-frame call here WOULD return a different product.  That
        is precisely the "changes its mind under occlusion" failure — and
        the tracker's visibility gate is what stops us from ever calling it
        in that situation.  A passing test therefore demonstrates the fix.
    """

    H_BINS = 18
    S_BINS = 4

    def __init__(
        self,
        color_map: Dict[str, Tuple[int, int, int]],
        sat_min: int = 90,
        val_min: int = 60,
    ) -> None:
        self.color_map = dict(color_map)
        self.sat_min = sat_min
        self.val_min = val_min
        # Build a reference DB by embedding a solid patch of each colour.
        self.db: EmbeddingDB = {}
        for name, bgr in self.color_map.items():
            patch = np.zeros((40, 40, 3), dtype=np.uint8)
            patch[:] = bgr
            self.db[name] = [self.embed(patch)]

    def embed(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0:
            return np.zeros(self.H_BINS * self.S_BINS, dtype=np.float32)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]
        mask = ((s >= self.sat_min) & (v >= self.val_min)).astype(np.uint8) * 255
        if int(np.count_nonzero(mask)) == 0:
            # No colourful pixels -> nothing recognisable here.
            return np.zeros(self.H_BINS * self.S_BINS, dtype=np.float32)
        hist = cv2.calcHist([hsv], [0, 1], mask,
                            [self.H_BINS, self.S_BINS],
                            [0, 180, 0, 256]).flatten().astype(np.float32)
        n = float(np.linalg.norm(hist))
        return hist / n if n > 0 else hist

    def analyze(self, crop: np.ndarray) -> Tuple[np.ndarray, dict]:
        emb = self.embed(crop)
        if not np.any(emb):
            # Deterministic "uncertain" verdict for an empty/greyscale crop.
            return emb, {
                "top_name": "uncertain", "top_score": 0.0, "margin": 0.0,
                "confident": False, "rankings": [],
            }
        return emb, match(emb, db=self.db)

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return _cosine(a, b)
