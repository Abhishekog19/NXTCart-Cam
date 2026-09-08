# ---------------------------------------------------------------
# build_db.py
#
# WHAT IT DOES
# ─────────────
# Walks through every image in references/<product_name>/, CROPS each one to
# just the product (the same crop the live path applies, so references and
# live crops share one framing domain), and runs the crop through the
# embedding extractor plus a colour fingerprint.  References that cannot be
# cropped confidently (ambiguous / too small / blank) are REJECTED, not
# embedded, so a mis-cropped photo never poisons a SKU.  The resulting vectors
# are saved to a single file (embedding_db.pkl) that matcher.py / verifier.py
# read.
#
# You must re-run this script every time you:
#   • Add new reference photos for an existing product
#   • Add a brand-new product folder
#   • Delete reference photos
#   • Upgrade the code's colour fingerprint format (the saved database is
#     stamped with a colour_format version; a stale one disables colour)
#
# HOW TO RUN
# ──────────
#   python build_db.py
#
# Expected output (example):
#   Processing: cola_can  (6 image(s))
#     001.jpg -> embedding shape (1280,)  (crop 62% of frame)  +colour
#     REJECT 007.jpg: AMBIGUOUS (two comparable regions in frame).
#     ...
#   Saved database: 2 product(s), 11 reference(s) kept, 2 rejected
#     [backend onnx-mbv2-1280, colour v2] -> embedding_db.pkl
# ---------------------------------------------------------------

import os
import pickle

import cv2

from ml.config import COLOUR_FORMAT_VERSION, DATABASE_PATH, REFERENCES_DIR
from ml.embedding_extractor import EMBEDDING_DIM, backend_id, extract_embedding
from ml.product_crop import CropStatus, crop_product
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
    total_rejected = 0  # reference photos skipped because they wouldn't crop

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
        rejected = 0

        for fname in image_files:
            fpath = os.path.join(product_path, fname)

            try:
                img = cv2.imread(fpath)
                if img is None:
                    print(f"    WARNING: Could not read {fname}; skipping.")
                    rejected += 1
                    continue

                # Crop to the product the SAME way the live path does, so the
                # reference and a live crop share one framing domain.  An
                # ambiguous / too-small / blank reference is REJECTED rather
                # than embedded — a mis-cropped reference would poison the SKU.
                res = crop_product(img)
                if not res.ok:
                    print(f"    REJECT {fname}: {res.status} ({res.reason}).")
                    rejected += 1
                    continue

                # Embed + colour the SAME crop, so appearance and colour
                # references are paired to one product view.
                embedding = extract_embedding(res.crop)
                hist = colour_hist(res.crop)
                embeddings.append(embedding)
                hists.append(hist)
                print(f"    {fname} -> embedding shape {embedding.shape}"
                      f"  (crop {res.area_frac * 100:.0f}% of frame)"
                      f"{'  +colour' if hist is not None and hist.any() else ''}")
            except Exception as e:
                print(f"    WARNING: Could not process {fname}: {e}")
                rejected += 1

        total_rejected += rejected
        if embeddings:
            database[product_name] = embeddings
            colours[product_name] = hists
            print(f"  => {len(embeddings)} reference(s) kept for "
                  f"'{product_name}', {rejected} rejected.\n")
        else:
            print(f"  => NO usable references for '{product_name}' "
                  f"({rejected} rejected). This SKU will be UNAVAILABLE.\n")

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
        # Per-SKU colour histograms, paired one-to-one with the photos in
        # "products".  ml/matcher.py ignores unknown keys, so an older matcher
        # still loads this file unchanged; ml/verifier.py reads it for the
        # colour channel.
        "colours": colours,
        # Colour fingerprint format version.  ml/verifier.load_colour_db
        # REFUSES a database whose colour_format is not the version its code
        # expects (an old-format vector has a different length and meaning),
        # disabling colour — MATCH unreachable — until this script is re-run.
        "colour_format": COLOUR_FORMAT_VERSION,
    }
    with open(DATABASE_PATH, "wb") as f:
        pickle.dump(payload, f)

    total_emb = sum(len(v) for v in database.values())
    print(f"Saved database: {len(database)} product(s), {total_emb} reference(s) "
          f"kept, {total_rejected} rejected [backend {payload['backend']}, "
          f"colour v{COLOUR_FORMAT_VERSION}] -> {DATABASE_PATH}")
    return database


if __name__ == "__main__":
    build_database()
