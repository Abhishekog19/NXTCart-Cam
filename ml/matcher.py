# ---------------------------------------------------------------
# ml/matcher.py
#
# WHAT IT DOES
# ─────────────
# Given the embedding of a new (unknown) product image, this module
# compares it against every embedding stored in the reference
# database and decides:
#
#   • Which product is the best match
#   • How confident we are (score + margin above threshold?)
#
# KEY CONCEPT — Cosine Similarity
# ─────────────────────────────────
# After L2-normalisation (done in embedding_extractor.py) two
# embeddings can be compared with a dot product.  The result is
# always in [-1, 1]:
#
#   1.0  → identical direction  (very similar images)
#   0.0  → perpendicular        (completely unrelated)
#  -1.0  → opposite             (very rare in practice)
#
# For each *product* we take the MAXIMUM similarity across all of
# its reference images (not an average).  This means: if even ONE
# of the reference photos is a good angle match, the product wins —
# which is exactly what we want when photos come from different
# positions.
# ---------------------------------------------------------------

import pickle
from typing import Optional

import numpy as np

from ml.config import DATABASE_PATH, MARGIN_THRESHOLD, SCORE_THRESHOLD


# ── Type alias for clarity ────────────────────────────────────────
# The database structure that build_db.py saves:
#   {
#     "cola_can":  [emb_1, emb_2, …, emb_8],  ← list of 1280-D vectors
#     "chips_bag": [emb_1, …, emb_6],
#     …
#   }
EmbeddingDB = dict[str, list[np.ndarray]]

# Module-level cache — load the DB only once per process.
_db_cache: Optional[EmbeddingDB] = None


def load_database(path: str = DATABASE_PATH) -> EmbeddingDB:
    """
    Load (or return the cached) embedding database from disk.

    The database is a plain Python dict saved with pickle.
    Keys are product names; values are lists of embedding vectors.

    Raises
    ------
    FileNotFoundError – if build_db.py hasn't been run yet.
    """
    global _db_cache

    if _db_cache is not None:
        return _db_cache

    try:
        with open(path, "rb") as f:
            _db_cache = pickle.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Embedding database not found at '{path}'.\n"
            "Run   python build_db.py   first to generate it."
        )

    n_products = len(_db_cache)
    n_refs = sum(len(v) for v in _db_cache.values())
    print(f"[matcher] Database loaded: {n_products} products, {n_refs} reference embeddings.")
    return _db_cache


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two *already-normalised* vectors.

    Because both vectors have length 1 (unit vectors), the cosine
    similarity is simply their dot product — no division needed.
    This is fast and exact.
    """
    return float(np.dot(a, b))


def match(
    query_embedding: np.ndarray,
    db: Optional[EmbeddingDB] = None,
) -> dict:
    """
    Compare a query embedding against the entire reference database
    and return a structured result.

    Parameters
    ----------
    query_embedding : numpy.ndarray, shape (1280,)
        The embedding of the image you want to identify.
        Must already be L2-normalised (embedding_extractor does this).

    db : EmbeddingDB, optional
        Pass a pre-loaded database to avoid re-reading from disk.
        If None, the database is loaded (or returned from cache).

    Returns
    -------
    dict with keys:
        "top_name"    (str)   – name of the best-matching product
        "top_score"   (float) – cosine similarity of the best match (0-1)
        "margin"      (float) – gap between #1 and #2 scores
        "confident"   (bool)  – True if both thresholds are met
        "rankings"    (list)  – all products sorted best→worst
                                each item: {"name": str, "score": float}

    Edge cases
    ----------
    • Single product in DB → margin is 1.0 (trivially confident if
      score is above threshold).
    • Empty DB → raises ValueError.
    """
    if db is None:
        db = load_database()

    if not db:
        raise ValueError("The embedding database is empty — run build_db.py.")

    # ── Compute each product's best score ────────────────────────
    # For each product: compute similarity against every reference
    # image, keep the maximum.  This is the "best-angle" approach.
    scores: list[tuple[float, str]] = []

    for product_name, ref_embeddings in db.items():
        sims = [_cosine_similarity(query_embedding, ref) for ref in ref_embeddings]
        best_sim = max(sims)  # single highest similarity for this product
        scores.append((best_sim, product_name))

    # Sort highest first.
    scores.sort(reverse=True, key=lambda x: x[0])

    top_score, top_name = scores[0]

    # ── Margin ────────────────────────────────────────────────────
    # How much better is #1 than #2?
    # A large margin means we're clearly seeing the right product.
    # A tiny margin means the model is confused between two products.
    if len(scores) >= 2:
        second_score = scores[1][0]
        margin = top_score - second_score
    else:
        # Only one product → no competition, treat margin as perfect.
        margin = 1.0

    # ── Confidence decision ───────────────────────────────────────
    # BOTH conditions must hold:
    #   1. The top score is good enough on its own.
    #   2. The gap over #2 is large enough to be sure we picked the right one.
    confident = (top_score >= SCORE_THRESHOLD) and (margin >= MARGIN_THRESHOLD)

    # ── Build full ranking for display ───────────────────────────
    rankings = [{"name": name, "score": score} for score, name in scores]

    return {
        "top_name": top_name,
        "top_score": round(top_score, 4),
        "margin": round(margin, 4),
        "confident": confident,
        "rankings": rankings,
    }
