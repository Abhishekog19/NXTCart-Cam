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

from ml.config import DATABASE_PATH, SCORE_THRESHOLD

# Minimum gap between the #1 and #2 product scores to be considered confident.
# zone_tracker uses top_score directly, so this only affects the 'confident' field.
_MARGIN_THRESHOLD = 0.03


# ── Type alias for clarity ────────────────────────────────────────
# The product mapping that build_db.py saves:
#   {
#     "cola_can":  [emb_1, emb_2, …, emb_8],  ← list of 1280-D vectors
#     "chips_bag": [emb_1, …, emb_6],
#     …
#   }
EmbeddingDB = dict[str, list[np.ndarray]]

# ── On-disk format ────────────────────────────────────────────────
# The pickle wraps the product mapping together with a stamp identifying
# WHICH embedding backend produced the vectors:
#
#   {"backend": "onnx-mbv2-1280", "dim": 1280, "products": {name: [emb, …]}}
#
# WHY: ml/embedding_extractor.py has two backends (fast ONNX float, legacy
# quantized TFLite) and they produce numerically incompatible vectors.
# Comparing a query from one against a database built with the other does
# not fail — it silently returns confident nonsense.  The stamp turns that
# into a loud, actionable error instead.
#
# The stamp lives INSIDE the wrapper, never as a bare top-level key,
# because match() iterates the product mapping directly — a loose key
# would be treated as a product name.
_PRODUCTS_KEY = "products"
_BACKEND_KEY = "backend"

# Module-level cache — load the DB only once per process.
_db_cache: Optional[EmbeddingDB] = None


def _rebuild_error(path: str, detail: str) -> FileNotFoundError:
    return FileNotFoundError(
        f"{detail}\n"
        f"  Database: {path}\n\n"
        f"Rebuild it from your reference photos:\n"
        f"    python build_db.py"
    )


def load_database(path: str = DATABASE_PATH) -> EmbeddingDB:
    """
    Load (or return the cached) embedding database from disk.

    Returns the product mapping: keys are product names, values are lists
    of embedding vectors.

    Raises
    ------
    FileNotFoundError – if build_db.py hasn't been run yet, or if the
        database on disk was built with a different embedding backend and
        would produce meaningless similarities.  Both cases are fixed the
        same way, by re-running build_db.py, so they share one error type.
    """
    global _db_cache

    if _db_cache is not None:
        return _db_cache

    try:
        with open(path, "rb") as f:
            raw = pickle.load(f)
    except FileNotFoundError:
        raise _rebuild_error(path, "Embedding database not found.")

    if not isinstance(raw, dict):
        raise _rebuild_error(
            path, f"Embedding database is a {type(raw).__name__}, not a dict.")

    # ── Verify the vectors were made by the backend we are running ──
    if _PRODUCTS_KEY in raw:
        from ml.embedding_extractor import backend_id

        stored = raw.get(_BACKEND_KEY, "unknown")
        current = backend_id()
        if stored != current:
            raise _rebuild_error(
                path,
                f"Embedding database was built with a different backend.\n"
                f"  Database backend : {stored}\n"
                f"  Current backend  : {current}\n"
                f"The two produce incompatible embedding spaces, so the\n"
                f"similarities would be meaningless.")
        db = raw[_PRODUCTS_KEY]
    else:
        # Pre-stamp database: produced before the backend swap, so its
        # vectors are from the old quantized-TFLite space no matter what we
        # are running now.  Refuse rather than guess.
        raise _rebuild_error(
            path,
            "Embedding database is in the old unstamped format, so its\n"
            "vectors cannot be matched to the current embedding backend.")

    if not isinstance(db, dict) or not db:
        raise _rebuild_error(path, "Embedding database contains no products.")

    _db_cache = db
    n_products = len(db)
    n_refs = sum(len(v) for v in db.values())
    print(f"[matcher] Database loaded: {n_products} products, "
          f"{n_refs} reference embeddings "
          f"(backend {raw.get(_BACKEND_KEY, '?')}).")
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
    confident = (top_score >= SCORE_THRESHOLD) and (margin >= _MARGIN_THRESHOLD)

    # ── Build full ranking for display ───────────────────────────
    rankings = [{"name": name, "score": score} for score, name in scores]

    return {
        "top_name": top_name,
        "top_score": round(top_score, 4),
        "margin": round(margin, 4),
        "confident": confident,
        "rankings": rankings,
    }
