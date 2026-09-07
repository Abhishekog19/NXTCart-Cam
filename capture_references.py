# ---------------------------------------------------------------
# capture_references.py  --  GUIDED REFERENCE CAPTURE (SOP-driven)
#
# WHAT IT DOES
# ─────────────
# Opens your camera and walks you through a FIXED SET OF POSES for each
# product, so the reference set covers the ways the item will actually be
# seen at the lane — not eight near-identical front shots.  For each pose it
# shows a live "usable view" indicator (the SAME test the live verifier
# uses, ml/visibility.py) so you only ever save frames that are actually
# judgeable, and it refuses to let you finish a product with too few photos.
#
# Photos are still saved exactly where build_db.py expects them:
#   references/<product_name>/001.jpg, 002.jpg, …
# so the existing insertion workflow is unchanged — this only makes the
# photos you feed it better and more consistent.  See REFERENCE_SOP.md for
# the why behind each pose.
#
# WHY POSES MATTER (acceptance rule 4)
# ─────────────────────────────────────
# The verifier compares a live crop to its BEST-matching reference.  If the
# references only show the front face, a shopper holding the item sideways
# scores low on appearance for no good reason.  Capturing each side, a
# rotation, a hand-grip, and a tilt gives the "best angle" match something
# to actually match against — and shooting on the DEPLOYMENT camera keeps
# the reference and live image domains the same.
#
# HOW TO RUN
# ──────────
#   python capture_references.py
# ---------------------------------------------------------------

import os
import sys

import cv2

from ml.config import CAMERA_INDEX, REFERENCES_DIR
from ml.visibility import assess

# The guided pose script.  Each entry is (label, on-screen instruction).
# Keep this list short enough to be quick but broad enough to cover how the
# item is really seen.  Order matters only for the operator's flow.
POSES = [
    ("front",     "FRONT face square to the camera"),
    ("back",      "BACK face square to the camera"),
    ("left",      "LEFT side / spine toward the camera"),
    ("right",     "RIGHT side / spine toward the camera"),
    ("rotated",   "Rotated ~45 degrees (a natural in-hand angle)"),
    ("hand_grip", "HELD in a hand, the way a shopper would carry it"),
    ("tilt",      "Tilted up/down (top or bottom partly visible)"),
]

# Minimum photos before a product may be considered done.  One clean shot
# per pose is the floor; more is better.
MIN_PHOTOS = 5


def _draw_guide(display, product_name, pose_label, pose_hint, saved,
                pose_idx, usable, reason):
    cv2.putText(display, f"Product: {product_name}   Saved: {saved}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(display,
                f"Pose {pose_idx + 1}/{len(POSES)}: {pose_label}",
                (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
    cv2.putText(display, pose_hint, (10, 82),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # Live usable-view indicator — the same assess() the verifier will use.
    if usable:
        cv2.putText(display, "VIEW OK - SPACE to save", (10, 112),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 0), 2)
    else:
        cv2.putText(display, f"VIEW POOR ({reason}) - adjust", (10, 112),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 120, 255), 2)

    cv2.putText(display,
                "SPACE=save  N=next pose  Q=done product",
                (10, display.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)


def capture_for_product(product_name: str, cap: cv2.VideoCapture) -> int:
    save_dir = os.path.join(REFERENCES_DIR, product_name)
    os.makedirs(save_dir, exist_ok=True)

    existing = [f for f in os.listdir(save_dir) if f.endswith(".jpg")]
    counter = len(existing) + 1

    print(f"\n[capture] Product: '{product_name}'")
    print(f"[capture] Saving to: {save_dir}")
    print(f"[capture] Walk through {len(POSES)} poses. SPACE saves the current "
          f"view, N moves to the next pose, Q finishes.\n")

    window_name = f"Capturing: {product_name}"
    saved = 0
    pose_idx = 0

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[capture] ERROR: Could not read camera frame.")
            break

        # Judge the WHOLE frame as the stand-in crop here.  At capture time we
        # do not run the detector, so we assess the centre region the operator
        # is framing the product into.
        vis = assess(frame)
        display = frame.copy()
        label, hint = POSES[pose_idx]
        _draw_guide(display, product_name, label, hint, saved, pose_idx,
                    vis.usable, vis.reason)
        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            if not vis.usable:
                print(f"  Skipped save — view not usable ({vis.reason}). "
                      f"Adjust framing/lighting and try again.")
                continue
            filename = os.path.join(save_dir, f"{counter:03d}.jpg")
            cv2.imwrite(filename, frame)
            saved += 1
            counter += 1
            print(f"  Saved {filename}  (pose: {label}, {saved} total)")
            # Advance to the next pose automatically after a save.
            if pose_idx < len(POSES) - 1:
                pose_idx += 1
        elif key in (ord("n"), ord("N")):
            pose_idx = (pose_idx + 1) % len(POSES)
        elif key in (ord("q"), ord("Q")):
            if saved < MIN_PHOTOS:
                print(f"  Only {saved} photo(s) — need at least {MIN_PHOTOS}. "
                      f"Keep going (or press Q again to force-finish).")
                # Require a second Q to override, so an accidental Q doesn't
                # leave a thin reference set.
                key2 = cv2.waitKey(0) & 0xFF
                if key2 not in (ord("q"), ord("Q")):
                    continue
            print(f"[capture] Done with '{product_name}'. {saved} photo(s).")
            break

    cv2.destroyWindow(window_name)
    return saved


def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera index {CAMERA_INDEX}. "
              f"Try changing CAMERA_INDEX in ml/config.py.")
        sys.exit(1)

    print("=" * 60)
    print("  NXTCart-Cam — Guided Reference Capture")
    print("=" * 60)
    print(f"  Camera index : {CAMERA_INDEX}")
    print(f"  Save location: {REFERENCES_DIR}")
    print(f"  Poses/product: {[p[0] for p in POSES]}")
    print(f"  Min photos   : {MIN_PHOTOS}")
    print("  See REFERENCE_SOP.md for the full procedure.")
    print("=" * 60)

    total_products = 0
    total_photos = 0

    while True:
        print()
        name = input("Enter product name (ENTER with no name to finish): ").strip()
        if not name:
            print("[capture] Finished capturing references.")
            break

        safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_"
                            for c in name)
        if safe_name != name:
            print(f"[capture] Using folder name: '{safe_name}'")

        saved = capture_for_product(safe_name, cap)
        total_products += 1
        total_photos += saved

    cap.release()
    cv2.destroyAllWindows()

    print(f"\n[capture] Summary: {total_products} product(s), "
          f"{total_photos} photo(s).")
    print("[capture] Next step: run   python build_db.py   to compute "
          "embeddings + colour references.")


if __name__ == "__main__":
    main()
