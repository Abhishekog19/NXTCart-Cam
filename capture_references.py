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
# so the existing insertion workflow is unchanged.  What IS saved is the
# CROPPED product (via ml/product_crop.crop_product), the same crop the live
# path applies, so references and live crops share one framing domain — and a
# frame the cropper cannot resolve confidently cannot be saved at all.
#
# WHICH CAMERA  (this decides more than it looks)
# ─────────────
# Capture runs through the SAME frame source the verifier uses
# (ml/frame_source.make_frame_source), selected by --source.
#
# A reference photo does not just record a product — it records that product
# AS SEEN BY ONE CAMERA.  Sensor noise, white balance, lens softness and JPEG
# quality are all baked in.  So references shot on the ESP32-CAM and live crops
# from a webcam (or vice versa) sit in two different image domains, and genuine
# items score low for a reason that has nothing to do with the product.
#
# Hence acceptance rule 0: shoot on the camera you will deploy, in its mounted
# position.  And hence, while the ESP32-vs-webcam bake-off is running, ONE
# REFERENCE SET PER CAMERA:
#
#   py -3 capture_references.py --source mjpeg  --out references_esp32
#   py -3 capture_references.py --source webcam --out references_webcam
#
# Photos are saved where build_db.py expects them, under whichever --out you
# give:  <out>/<product_name>/001.jpg, 002.jpg, …
#
# WHY POSES MATTER (acceptance rule 4)
# ─────────────────────────────────────
# The verifier compares a live crop to its BEST-matching reference.  If the
# references only show the front face, a shopper holding the item sideways
# scores low on appearance for no good reason.  Capturing each side, a
# rotation, a hand-grip, and a tilt gives the "best angle" match something
# to actually match against.
#
# HOW TO RUN
# ──────────
#   py -3 capture_references.py --source webcam --out references_webcam
# ---------------------------------------------------------------

import argparse
import os
import sys

import cv2
import numpy as np

from ml.config import CAMERA_SOURCE, REFERENCES_DIR
from ml.frame_source import make_frame_source
from ml.product_crop import crop_product
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
                pose_idx, can_save, status_text):
    cv2.putText(display, f"Product: {product_name}   Saved: {saved}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(display,
                f"Pose {pose_idx + 1}/{len(POSES)}: {pose_label}",
                (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
    cv2.putText(display, pose_hint, (10, 82),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # Live indicator — reflects BOTH that the product could be cropped AND that
    # the crop is a usable view (the same assess() the verifier will use).
    if can_save:
        cv2.putText(display, f"{status_text} - SPACE to save", (10, 112),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 0), 2)
    else:
        cv2.putText(display, f"{status_text} - adjust", (10, 112),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 120, 255), 2)

    cv2.putText(display,
                "SPACE=save  N=next pose  Q=done product",
                (10, display.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)


def capture_for_product(product_name: str, source,
                        references_dir: str = REFERENCES_DIR) -> int:
    save_dir = os.path.join(references_dir, product_name)
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
        ok, frame, _meta = source.read()
        if not ok or frame is None:
            # A source that is merely reconnecting (ESP32-CAM over WiFi)
            # returns a transient miss but is NOT stopped — keep the UI alive
            # and wait rather than aborting the capture.
            if not getattr(source, "stopped", True):
                wait = np.zeros((240, 480, 3), dtype=np.uint8)
                cv2.putText(wait, "Waiting for camera stream...", (12, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 170, 255), 1)
                cv2.imshow(window_name, wait)
                if (cv2.waitKey(30) & 0xFF) in (ord("q"), ord("Q")):
                    break
                continue
            print("[capture] ERROR: camera stopped / could not read frame.")
            break

        # Crop to the product the SAME way build_db.py and the live path do, so
        # what we SAVE is exactly what will be embedded and matched.  Only when
        # the crop resolves AND is a usable view can this frame be saved.
        res = crop_product(frame)
        display = frame.copy()
        if res.ok:
            vis = assess(res.crop)
            can_save = vis.usable
            status_text = "VIEW OK" if vis.usable else f"VIEW POOR ({vis.reason})"
        else:
            can_save = False
            status_text = f"NO CROP ({res.status})"

        # Show the crop box so the operator sees exactly what will be stored.
        if res.bbox is not None:
            x, y, w, h = res.bbox
            box_col = (0, 230, 0) if can_save else (0, 120, 255)
            cv2.rectangle(display, (x, y), (x + w, y + h), box_col, 2)

        label, hint = POSES[pose_idx]
        _draw_guide(display, product_name, label, hint, saved, pose_idx,
                    can_save, status_text)
        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            if not can_save:
                print(f"  Skipped save - {status_text}. "
                      f"Adjust framing/lighting and try again.")
                continue
            filename = os.path.join(save_dir, f"{counter:03d}.jpg")
            # Save the CROP, not the whole frame.
            cv2.imwrite(filename, res.crop)
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
                print(f"  Only {saved} photo(s) - need at least {MIN_PHOTOS}. "
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
    ap = argparse.ArgumentParser(
        description="Guided reference-photo capture (see REFERENCE_SOP.md).")
    # ── which camera, and where its references go ─────────────────
    # These two flags exist for one reason: THE REFERENCE SET IS
    # CAMERA-SPECIFIC.  A reference photo encodes the image domain of the
    # camera that shot it, so the ESP32-CAM and the webcam each need their own
    # set and their own database.  Selecting the camera by editing ml/config.py
    # between runs is how you end up with a reference set that is half ESP32
    # and half webcam - which looks completely normal on disk and quietly
    # wrecks every accuracy number that follows.  See DEPLOYMENT.md section 6.
    ap.add_argument("--source", default=CAMERA_SOURCE,
                    choices=["webcam", "mjpeg"],
                    help=f"frame source: webcam (USB) or mjpeg (ESP32-CAM). "
                         f"Default: {CAMERA_SOURCE}")
    ap.add_argument("--url", default=None,
                    help="MJPEG stream URL when --source mjpeg "
                         "(default: ESP32_STREAM_URL from ml/config.py)")
    ap.add_argument("--index", type=int, default=None,
                    help="webcam device index when --source webcam")
    ap.add_argument("--out", default=REFERENCES_DIR,
                    help=f"directory to save reference photos into. Use a "
                         f"per-camera directory, e.g. references_esp32/ or "
                         f"references_webcam/. Default: {REFERENCES_DIR}")
    args = ap.parse_args()

    references_dir = args.out
    os.makedirs(references_dir, exist_ok=True)

    try:
        source = make_frame_source(args.source, url=args.url, index=args.index)
    except Exception as e:
        print(f"ERROR: Cannot open camera source '{args.source}': {e}\n"
              f"For a webcam, try --index 1. For the ESP32-CAM, check the "
              f"stream URL opens in a browser first.")
        sys.exit(1)

    print("=" * 60)
    print("  NXTCart-Cam - Guided Reference Capture")
    print("=" * 60)
    print(f"  Camera source: {args.source}")
    print(f"  Save location: {references_dir}")
    print(f"  Poses/product: {[p[0] for p in POSES]}")
    print(f"  Min photos   : {MIN_PHOTOS}")
    print("  Saved photos are CROPPED to the product (same crop as the live")
    print("  path). See REFERENCE_SOP.md for the full procedure.")
    print("=" * 60)

    total_products = 0
    total_photos = 0

    try:
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

            saved = capture_for_product(safe_name, source, references_dir)
            total_products += 1
            total_photos += saved
    finally:
        source.release()
        cv2.destroyAllWindows()

    print(f"\n[capture] Summary: {total_products} product(s), "
          f"{total_photos} photo(s).")
    print(f"[capture] Next step - build the database FOR THIS CAMERA:")
    print(f"    py -3 build_db.py --references {references_dir} "
          f"--out embedding_db_<camera>.pkl")


if __name__ == "__main__":
    main()
