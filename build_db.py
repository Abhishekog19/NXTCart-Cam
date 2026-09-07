# ---------------------------------------------------------------
# build_db.py
#
# WHAT IT DOES
# ─────────────
# Walks through every image in references/<product_name>/ and runs
# it through the embedding extractor.  The resulting vectors are
# saved to a single file (embedding_db.pkl) that matcher.py reads.
#
# You must re-run this script every time you:
#   • Add new reference photos for an existing product
#   • Add a brand-new product folder
#   • Delete reference photos
#
# HOW TO RUN
# ──────────
#   python build_db.py
#
# Expected output (example):
#   Processing: cola_can
#     001.jpg → embedding shape (1280,)
#     ...
#   Processing: chips_bag
#     ...
#   Saved database with 2 products, 13 embeddings → embedding_db.pkl
# ---------------------------------------------------------------

import os
import pickle

import cv2

from ml.config import DATABASE_PATH, REFERENCES_DIR
from ml.embedding_extractor import EMBEDDING_DIM, backend_id, extract_embedding
from ml.verifier import colour_hist

# Image extensions we'll look for.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def build_database() -> dict:
    """
    Scan the references/ directory, compute embeddings for every
    image, and save the result as a pickle file.

    Returns the database dict for inspection.
    """
    if not os.path.isdir(REFERENCES_DIR):
        print(
            f"ERROR: References directory not found: {REFERENCES_DIR}\n"
            "Run  python capture_references.py  first to create your reference photos."
        )
        return {}

    product_dirs = [
        d for d in os.listdir(REFERENCES_DIR)
        if os.path.isdir(os.path.join(REFERENCES_DIR, d))
    ]

    if not product_dirs:
        print(
            "ERROR: No product folders found inside references/.\n"
            "Run  python capture_references.py  to capture reference images."
        )
        return {}

    print(f"Found {len(product_dirs)} product folder(s): {product_dirs}\n")

    # database:  { product_name: [embedding_1, embedding_2, …] }
    database: dict[str, list] = {}
    # colours:   { product_name: [hist_1, hist_2, …] } — one per SAME photo,
    # so the verifier's colour channel has multiple references per SKU that
    # are paired to the appearance references above (acceptance rule 4).
    colours: dict[str, list] = {}

    for product_name in sorted(product_dirs):
        product_path = os.path.join(REFERENCES_DIR, product_name)

        # Collect all image files in this folder.
        image_files = sorted([
            f for f in os.listdir(product_path)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        ])

        if not image_files:
            print(f"  Skipping '{product_name}' — no images found.")
            continue

        print(f"Processing: {product_name}  ({len(image_files)} image(s))")
        embeddings = []
        hists = []

        for fname in image_files:
            fpath = os.path.join(product_path, fname)

            try:
                embedding = extract_embedding(fpath)
                # Read the SAME file for the colour histogram so appearance
                # and colour references are paired to one photo.
                img = cv2.imread(fpath)
                hist = colour_hist(img) if img is not None else None
                embeddings.append(embedding)
                hists.append(hist)
                print(f"    {fname} -> embedding shape {embedding.shape}"
                      f"{'  +colour' if hist is not None and hist.any() else ''}")
            except Exception as e:
                print(f"    WARNING: Could not process {fname}: {e}")

        if embeddings:
            database[product_name] = embeddings
            colours[product_name] = hists
            print(f"  => {len(embeddings)} embedding(s) stored for '{product_name}'.\n")

    if not database:
        print("ERROR: No embeddings were produced. Check your reference images.")
        return {}

    # ── Save to disk ──────────────────────────────────────────────
    # Wrap the product mapping with a stamp naming the backend that
    # produced these vectors.  ml/matcher.py refuses to load a database
    # whose stamp doesn't match the running backend, because the two
    # embedding spaces are incompatible and mixing them yields confident
    # nonsense rather than an error.  See ml/matcher.py for the format.
    payload = {
        "backend": backend_id(),
        "dim": EMBEDDING_DIM,
        "products": database,
        # NEW: per-SKU colour histograms, paired one-to-one with the photos
        # in "products".  ml/matcher.py ignores unknown keys, so an older
        # matcher still loads this file unchanged; ml/verifier.py reads it for
        # the colour channel.  Absent from pre-existing databases, which is
        # fine — the verifier treats a missing colour ref as "cannot pass
        # colour", never as "accept".
        "colours": colours,
    }
    with open(DATABASE_PATH, "wb") as f:
        pickle.dump(payload, f)

    total_emb = sum(len(v) for v in database.values())
    print(f"Saved database: {len(database)} product(s), {total_emb} embeddings "
          f"[backend {payload['backend']}] -> {DATABASE_PATH}")
    return database


if __name__ == "__main__":
    build_database()
