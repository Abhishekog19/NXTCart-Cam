# ---------------------------------------------------------------
# capture_references.py
#
# WHAT IT DOES
# ─────────────
# Opens your webcam and helps you build a reference photo set for
# each product.  For each product:
#   1. You type the product name at the terminal.
#   2. A live camera preview opens.
#   3. Press  SPACE  to save a numbered photo.
#   4. Press  Q      when you have enough photos, then move on to
#              the next product.
#
# Photos are saved to:
#   references/<product_name>/001.jpg
#   references/<product_name>/002.jpg
#   …
#
# RECOMMENDED: 5-8 photos per product, varied angles/distances.
#
# HOW TO RUN
# ──────────
#   python capture_references.py
# ---------------------------------------------------------------

import os
import sys

import cv2

from ml.config import CAMERA_INDEX, REFERENCES_DIR


def capture_for_product(product_name: str, cap: cv2.VideoCapture) -> int:
    """
    Show a live preview and let the user save frames for one product.

    Returns the number of photos saved.
    """
    # Create the output directory for this product.
    save_dir = os.path.join(REFERENCES_DIR, product_name)
    os.makedirs(save_dir, exist_ok=True)

    # Find the next available image number so we never overwrite existing ones.
    existing = [f for f in os.listdir(save_dir) if f.endswith(".jpg")]
    counter = len(existing) + 1  # e.g., if 3 photos already exist → start at 4

    print(f"\n[capture] Product: '{product_name}'")
    print(f"[capture] Saving to: {save_dir}")
    print("[capture] Controls:  SPACE = save photo  |  Q = done with this product\n")

    window_name = f"Capturing: {product_name}"
    saved = 0

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[capture] ERROR: Could not read camera frame. Check your camera.")
            break

        # Draw an on-screen guide so the user knows what to do.
        display = frame.copy()
        cv2.putText(
            display,
            f"Product: {product_name}  |  Saved: {saved}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            display,
            "SPACE = capture  |  Q = next product",
            (10, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (200, 200, 200),
            1,
        )

        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            # Save the current frame as a JPEG.
            filename = os.path.join(save_dir, f"{counter:03d}.jpg")
            cv2.imwrite(filename, frame)
            saved += 1
            counter += 1
            print(f"  Saved {filename}  ({saved} total)")

        elif key in (ord("q"), ord("Q")):
            print(f"[capture] Done with '{product_name}'. {saved} photo(s) saved.")
            break

    cv2.destroyWindow(window_name)
    return saved


def main():
    # Open the camera once and reuse it for all products.
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print(
            f"ERROR: Cannot open camera index {CAMERA_INDEX}.\n"
            "Try changing CAMERA_INDEX in ml/config.py."
        )
        sys.exit(1)

    print("=" * 60)
    print("  NXTCart-Cam — Reference Photo Capture")
    print("=" * 60)
    print(f"  Camera index : {CAMERA_INDEX}")
    print(f"  Save location: {REFERENCES_DIR}")
    print("=" * 60)

    total_products = 0
    total_photos = 0

    while True:
        print()
        name = input("Enter product name (or press ENTER with no name to finish): ").strip()

        if not name:
            print("[capture] Finished capturing references.")
            break

        # Sanitise the name so it's safe to use as a folder name.
        # Replace spaces with underscores, remove odd characters.
        safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
        if safe_name != name:
            print(f"[capture] Using folder name: '{safe_name}'")

        saved = capture_for_product(safe_name, cap)
        total_products += 1
        total_photos += saved

    cap.release()
    cv2.destroyAllWindows()

    print(f"\n[capture] Summary: {total_products} product(s), {total_photos} photo(s) captured.")
    print("[capture] Next step: run   python build_db.py   to compute embeddings.")


if __name__ == "__main__":
    main()
