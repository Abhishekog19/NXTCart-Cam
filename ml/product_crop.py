# ---------------------------------------------------------------
# ml/product_crop.py  --  ONE CROP FOR REFERENCES AND LIVE INPUT
#
# WHY THIS FILE EXISTS
# ─────────────────────
# The verifier compares a live crop of the moving item to the stored
# reference crops of a SKU.  That comparison is only fair if both were
# framed the same way.  Before this module, references were saved as WHOLE
# frames while the live path fed the detector's tight product crop — two
# different framing domains, so a genuine match scored low for no real
# reason.  crop_product() is the single definition of "cut the frame down
# to just the product", used by BOTH build_db.py (references) and the
# capture tool, so references and live inputs finally live in one domain.
#
# HOW IT FINDS THE PRODUCT (and why it can REFUSE)
# ─────────────────────────────────────────────────
# It thresholds GRADIENT (Sobel) energy, not brightness.  A plain surface
# has almost no gradient; a product's print and edges have a lot — and this
# is true whether the product is lighter OR darker than the surface, so it
# is polarity-independent (a brightness threshold would need to know which).
# Then, exactly like the live follower, it REFUSES to guess when the scene
# is ambiguous: two comparably-large gradient regions ⇒ AMBIGUOUS (reject),
# a product too small in frame ⇒ TOO_SMALL (reject), a blank frame ⇒ EMPTY.
# A rejected reference is skipped by build_db.py rather than poisoning the
# database with a mis-cropped fingerprint.
# ---------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from ml.config import (
    CROP_AMBIG_RATIO,
    CROP_MARGIN,
    CROP_MIN_AREA_FRAC,
    CROP_MIN_PX,
)


class CropStatus:
    """Outcome of a crop attempt.  Only OK is safe to embed / store."""
    OK = "OK"
    EMPTY = "EMPTY"          # no product-like texture found (blank/plain frame)
    TOO_SMALL = "TOO_SMALL"  # product doesn't fill enough of the frame
    AMBIGUOUS = "AMBIGUOUS"  # 2+ comparable regions — can't tell which is THE product


@dataclass
class CropResult:
    crop: Optional[np.ndarray]
    status: str
    bbox: Optional[Tuple[int, int, int, int]]  # x, y, w, h in source pixels
    area_frac: float
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == CropStatus.OK


def _gradient_mask(gray: np.ndarray) -> Optional[np.ndarray]:
    """
    Binary mask of where the image has strong gradient (product print/edges).

    Returns None when the frame is essentially flat (no gradient anywhere),
    which the caller reports as EMPTY.
    """
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mean_mag = float(mag.mean())
    if mean_mag <= 1e-6:
        return None
    # Threshold well above the frame's mean gradient so smooth background is
    # excluded, with an absolute floor so faint sensor/JPEG noise on a plain
    # surface never masks in.  A real product's texture sits far above both.
    thr = max(mean_mag * 1.5, 8.0)
    mask = (mag >= thr).astype(np.uint8) * 255
    # Close small gaps so a textured product becomes ONE blob rather than many
    # speckles, then a light dilate to recover the edge the threshold shaved.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.dilate(mask, k, iterations=1)
    return mask


def crop_product(image: np.ndarray, margin: Optional[float] = None) -> CropResult:
    """
    Crop `image` down to the single product in it.

    Returns a CropResult; only `status == OK` yields a usable `.crop`.  The
    non-OK statuses (EMPTY / TOO_SMALL / AMBIGUOUS) are deliberate refusals,
    so the caller can skip a reference or warn an operator instead of storing
    a mis-cropped fingerprint.
    """
    if image is None or getattr(image, "size", 0) == 0:
        return CropResult(None, CropStatus.EMPTY, None, 0.0, "empty image")

    margin = CROP_MARGIN if margin is None else margin
    h_img, w_img = image.shape[:2]
    frame_area = float(h_img * w_img)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    mask = _gradient_mask(gray)
    if mask is None or int(np.count_nonzero(mask)) == 0:
        return CropResult(None, CropStatus.EMPTY, None, 0.0,
                          "no product-like texture (frame looks blank)")

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return CropResult(None, CropStatus.EMPTY, None, 0.0, "no contour found")

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    x, y, w, h = cv2.boundingRect(contours[0])
    area_frac = float(w * h) / frame_area

    # Ambiguity: a SECOND region nearly as large as the largest, not enclosed
    # by it, means two things are in shot.  Refuse rather than guess — the same
    # stance the live follower takes when two detections contest the target.
    if len(contours) >= 2:
        a0 = cv2.contourArea(contours[0]) or 1.0
        a1 = cv2.contourArea(contours[1])
        x1, y1, w1, h1 = cv2.boundingRect(contours[1])
        enclosed = (x <= x1 and y <= y1 and x1 + w1 <= x + w and y1 + h1 <= y + h)
        if a1 >= CROP_AMBIG_RATIO * a0 and not enclosed:
            return CropResult(None, CropStatus.AMBIGUOUS, (x, y, w, h), area_frac,
                              "two comparable regions in frame")

    if area_frac < CROP_MIN_AREA_FRAC:
        return CropResult(None, CropStatus.TOO_SMALL, (x, y, w, h), area_frac,
                          f"product fills only {area_frac * 100:.0f}% of the frame")

    # Pad the box, clamp to the frame.
    mx, my = int(round(w * margin)), int(round(h * margin))
    x0 = max(0, x - mx)
    y0 = max(0, y - my)
    x1 = min(w_img, x + w + mx)
    y1 = min(h_img, y + h + my)
    if (x1 - x0) < CROP_MIN_PX or (y1 - y0) < CROP_MIN_PX:
        return CropResult(None, CropStatus.TOO_SMALL, (x, y, w, h), area_frac,
                          "cropped product smaller than the minimum")

    crop = image[y0:y1, x0:x1].copy()
    return CropResult(crop, CropStatus.OK, (x0, y0, x1 - x0, y1 - y0), area_frac, "ok")
