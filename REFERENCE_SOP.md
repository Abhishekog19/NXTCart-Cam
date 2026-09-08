# Reference Capture SOP — NXTCart-Cam

**Goal:** produce reference photos that let the camera answer *"is the item that
entered the cart the SKU the barcode says?"* reliably — and, critically, catch
the **same-weight swap** (scan a cheap item, drop in an expensive one of equal
weight). Weight can't see that; the camera must, via **appearance + colour**.

This is the procedure to run **tomorrow, on real products, with the real
camera**. Tonight's code is already validated on logic and plumbing; accuracy
depends entirely on the quality of the photos you capture here.

---

## 0. The one rule that matters most: shoot on the deployment camera

Capture references **through the ESP32-CAM in its mounted position**, not your
phone or laptop. The recognizer compares a live crop to the references; if the
references were shot on a crisp phone camera and the live feed is a low-res
ESP32-CAM at a downward angle under store lighting, the two live in *different
image domains* and genuine matches score low for no real reason.

- Same camera, same mount height/angle, same lens.
- Same lighting you'll demo under.
- If the ESP32-CAM sits **opposite the scanner**, capture from that same
  viewpoint — the side of the product the camera will actually see.

> Set `CAMERA_SOURCE = "mjpeg"` and `ESP32_STREAM_URL` in `ml/config.py`, then
> run `python capture_references.py`. Capture opens the camera through the **same**
> `make_frame_source(CAMERA_SOURCE)` the verifier uses, so `"mjpeg"` genuinely shoots
> *through the ESP32-CAM* — reference and live frames come off one pipeline. (Tonight it
> defaults to `"webcam"` for bench work.)

---

## 1. What the capture tool enforces for you

`python capture_references.py` walks a fixed **pose set** per product and, for each frame,
does two things before it will let you save:

1. **Crops to the product** with the *same* cropper the live path and `build_db.py` use
   (`ml/product_crop.py`) and **saves the crop, not the whole frame** — so a reference and
   a live crop share one framing domain. If the scene is ambiguous (two comparable items),
   the product is too small, or the frame is blank, it shows **NO CROP** and refuses to
   save — the same refusal `build_db.py` makes, caught at capture time instead of
   poisoning the DB later.
2. Runs the **VIEW OK / VIEW POOR** indicator on that crop — the *same* usable-view test
   the live verifier uses (`ml/visibility.py`) — so you only ever save crops the system
   can actually judge.

The crop box is drawn live (green = will save, orange = won't). It won't let you finish a
product with too few photos (`MIN_PHOTOS = 5`).

Poses (SPACE saves + auto-advances, `N` skips a pose, `Q` finishes):

| Pose        | Why it's in the set |
|-------------|---------------------|
| `front`     | The primary face; most scans present this. |
| `back`      | Barcode/back panel; often what the camera sees as it's set down. |
| `left`      | Spine/side — narrow profile the front refs don't cover. |
| `right`     | Opposite side; packaging often differs. |
| `rotated`   | ~45° — the natural in-hand angle, not a clean face. |
| `hand_grip` | Held the way a shopper carries it, **fingers partly occluding**. |
| `tilt`      | Tilted up/down so top/bottom is partly visible. |

Capturing these gives the verifier a *best-angle* reference to match against, so
a shopper holding the item sideways doesn't score low just because every
reference was a flat front shot.

---

## 2. Framing & lighting

- **Fill ~60–80% of the frame** with the product. Too small = the cropper reports
  `TOO_SMALL` and won't save; too large = edges clipped before the crop can pad them. The
  tool stores the **cropped product**, so present one clear item, well inside the frame.
- **Even, diffuse light.** Avoid a single hard lamp — glare blows out printing
  and kills the texture the visibility test and embedding rely on.
- **Plain, contrasting surface** behind the item (the deployment surface is
  ideal). Busy backgrounds leak into the crop.
- **Hold steady** — motion blur flattens texture and reads as VIEW POOR.
- Capture **5–8 clean frames per product minimum**, spread across the poses.
  More angles > more duplicates of the same angle.

### Low-saturation products (rice bags, white/beige cartons, clear bottles)
These are handled deliberately on two fronts. **Visibility** is judged by *texture +
edges, not colour*, so a white bag is never treated as invisible. And the **colour
fingerprint (v2)** now adds a *brightness* profile of the pale, unsaturated pixels — so a
white carton, a grey pouch, and a beige box are no longer identical all-zero vectors; each
gets a real "bright-and-colourless" signature. It's still coarser than a vivid product's
hue, so two similarly-bright pale products separate only weakly on colour. Lean on:
- crisp, well-lit shots so the **appearance** channel carries the decision, and
- capturing any **coloured cap/label/seam** that distinguishes the variant.

---

## 3. Same-weight pairs (the attack you're defending against)

For the demo, deliberately prepare **pairs of products with near-identical
weight but different appearance/colour**, e.g. two similarly-sized bottles or
boxes. Capture references for **both**. Then at demo time:

- Scan A, present A → expect **MATCH**.
- Scan A, present B (same weight, different colour) → expect **SUSPECT** (shape
  ok, colour wrong) or **MISMATCH** (appearance wrong). This is the case weight
  alone cannot catch.

Note the two honest failure directions, both safe:
- **SUSPECT** = appearance passed but colour disagreed → flag for review.
- **MISMATCH** = appearance failed → rejected outright, colour cannot rescue it.

---

## 4. Build the database

After capturing, from the project root:

```bash
python build_db.py
```

This writes `embedding_db.pkl` containing, **per photo**, both the appearance
embedding *and* a paired colour histogram (the `"colours"` block), each computed on the
**cropped** product so references and live crops match. A photo the cropper can't resolve
is reported `REJECT … (AMBIGUOUS / TOO_SMALL / EMPTY)` and skipped rather than stored
mis-framed. Re-run it **every time** you add/remove photos or products. Confirm the tail
line reports the product count, `[backend onnx-mbv2-1280]`, **and** `colour v2`.

> The colour fingerprint is **format-versioned**. If the DB's colour format is older than
> the code expects, the verifier prints `[verifier] Colour references are format …` and
> **disables colour** — MATCH becomes unreachable (SUSPECT at best, the safe direction) —
> until you rebuild. So after any code update that changes the colour format, re-run
> `build_db.py`.

---

## 5. Sanity-check before the review

1. `python test_verify.py` → **ALL CHECKS PASSED** (logic intact).
2. `python verify_demo.py` with the DB present:
   - Scan a product, carry it left→right into the cart-entry box, press `W` →
     **MATCH**.
   - Scan A, carry same-weight B → **SUSPECT / MISMATCH**.
   - Cover the item with your hand mid-transit → **RETRY** (broken custody).
   - Scan again mid-transit → old transaction **RETRY**, new one starts.
3. With **no** `embedding_db.pkl` present, the demo still starts and every scan
   resolves **UNAVAILABLE** — never a silent accept.

---

## 6. Running on the 2 GB Raspberry Pi (memory & latency)

The module is built to stay small on a Pi shared with the display and the other
sensors:

- **Crops are downscaled to `IMAGE_SIZE` (224) on capture**, so buffered memory
  is bounded regardless of how large the item appears on screen.
- **The crop buffer is capped** (`VERIFY_BURST_FRAMES`, thinned evenly across
  the trajectory) — it never grows with transaction length; peak is roughly
  `VERIFY_BURST_FRAMES × 224×224×3 B` ≈ a few MB.
- **One embedding per usable crop**, and only for the *followed* item — not
  every blob every frame.
- **MJPEG source keeps newest-frame-only** (a background reader drops stale
  frames), so a slow WiFi link can't back up a frame queue in RAM.
- Frames carry a **monotonic seq**; a re-read of one frame is deduped, so no
  wasted re-embedding and no double-counted vote.

Tuning knobs live in `ml/config.py` under the verification block
(`VERIFY_*`, `ASSOC_*`, `SCANNER_REGION`, `CART_ENTRY_REGION`, `VIS_*`). The
quoted ONNX inference (~6.5 ms) and sub-second latency are **targets until
measured on the Pi** — measure them there and adjust `VERIFY_BURST_FRAMES` /
`VERIFY_PASS_FRACTION` if you need to trade a little accuracy for headroom.

---

## 7. Hardware bring-up checklist (tomorrow)

- [ ] ESP32-CAM streaming; set `CAMERA_SOURCE="mjpeg"` + `ESP32_STREAM_URL`.
- [ ] Confirm `SCANNER_REGION` / `CART_ENTRY_REGION` match where items actually
      enter and land in the ESP32-CAM's view (they're frame fractions; adjust
      to the mounted framing).
- [ ] Barcode scanner (USB-HID) — replace `MockBarcodeSource` with a real `poll()`
      returning a `ScanEvent(sku, txn_id, ts)`; supply your backend's order/line id as
      `txn_id` so verdicts correlate. Seam is in `ml/events.py` (contract: DEPLOYMENT §8a).
- [ ] Arduino load cell over serial — replace `MockWeightSource` so `poll()` emits
      `CHANGING` then `SETTLED` (optionally tagged with the same `txn_id`). Seam is in
      `ml/events.py` (contract: DEPLOYMENT §8a).
- [ ] Capture references **through the ESP32-CAM**, build DB, run the checks in
      §5 on real products.
