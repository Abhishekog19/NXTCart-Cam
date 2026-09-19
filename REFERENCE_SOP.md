# Reference Capture SOP — NXTCart-Cam

**Goal:** produce reference photos that let the camera answer *"is the item that
entered the cart the SKU the barcode says?"* reliably — and, critically, catch
the **same-weight swap** (scan a cheap item, drop in an expensive one of equal
weight). Weight can't see that; the camera must, via **appearance + colour**.

Accuracy depends *entirely* on the quality of the photos you capture here. The
code is validated on logic and plumbing; it cannot invent detail the camera
never recorded.

> **Read this before you shoot anything.** The camera hardware is **not decided
> yet.** Two modules are live candidates — the ESP32-CAM and a USB webcam — and
> [DEPLOYMENT.md §6](DEPLOYMENT.md) runs a four-way bake-off to pick one on
> measured numbers. Until that bake-off is done, **everything in this SOP
> happens twice: once per camera, into separate directories.** §0 and §7 explain
> why that is not optional.

---

## 0. The rule that matters most: shoot on the camera you are testing

A reference photo does not just record a product. It records **that product as
seen by one specific camera** — sensor noise, white balance, lens softness, JPEG
compression and mount angle are all baked into the pixels.

The recognizer compares a live crop against those references. So if the
references were shot on a crisp webcam and the live feed is a soft, noisy
ESP32-CAM at a downward angle under store lighting, the two sit in **different
image domains**, and genuine items score low for a reason that has nothing to do
with the product. You would be measuring the mismatch you created in setup, not
the camera.

Hence the rule, in both phases of the project:

- **During the bake-off:** each candidate camera gets **its own reference set and
  its own database**. Never score ESP32-CAM crops against webcam references.
- **After the bake-off:** capture through the **winning camera in its final
  mounted position**, not your phone, not your laptop.

Concretely — same camera, same mount height and angle, same lens, same lighting
you will demo under. If the camera sits **opposite the scanner**, capture from
that same viewpoint: the side of the product the camera will actually see.

### Selecting the camera — by flag, not by config edit

```bash
# ESP32-CAM
py -3 capture_references.py --source mjpeg --url http://192.168.4.1:81/stream --out references_esp32

# USB webcam
py -3 capture_references.py --source webcam --index 0 --out references_webcam
```

Capture opens the camera through the **same** `make_frame_source()` the live
verifier uses, so `--source mjpeg` genuinely shoots *through the ESP32-CAM* —
reference and live frames come off one pipeline.

> **Why flags and not `ml/config.py`.** Switching cameras by editing config
> between runs is exactly how you end up with a reference set that is half ESP32
> and half webcam. On disk that looks completely normal — same folders, same
> filenames — and it quietly wrecks every accuracy number that follows. The
> `--source` / `--out` pair makes the camera part of the command you actually
> typed, and `--out` keeps the two sets physically apart.

| Camera | `--source` | Typical extra flag | Reference dir | Database |
|---|---|---|---|---|
| ESP32-CAM | `mjpeg` | `--url http://<ip>:81/stream` | `references_esp32/` | `embedding_db_esp32.pkl` |
| USB webcam | `webcam` | `--index 0` (try `1` if wrong device) | `references_webcam/` | `embedding_db_webcam.pkl` |

---

## 1. Camera settings to fix *before* the first photo

This section is new, and it is the part most likely to silently cost you
accuracy. **Set these once, then do not touch them again** — not between
products, not between the reference shoot and the dataset capture, not between
the two cameras' sessions.

Every setting below changes the image domain. Changing one mid-run splits your
own reference set into two domains and makes the resulting scores meaningless.

### 1a. ESP32-CAM (candidate A)

The ESP32-CAM's image quality is the known weak point of this design — it is the
whole reason the webcam is being evaluated against it. Squeeze what you can out
of it in firmware:

| Setting | Use | Why |
|---|---|---|
| `framesize` | **`FRAMESIZE_VGA` (640×480)** | Enough detail for the embedding; higher sizes stall the WiFi link and drop frames. |
| `quality` | **10–12** (lower = better JPEG) | Below ~10 the ESP32 runs out of buffer and stutters; above ~14 compression smears the label texture the embedding relies on. |
| `vflip` / `hmirror` | Match the physical mount | Fix the orientation **in firmware**, not by remounting later. |
| AWB (auto white balance) | **on** | Keeps colour stable across the shoot, which the colour histogram depends on. |
| AEC (auto exposure) | **on** | Prevents blown-out or black frames under changing store light. |
| `brightness` / `contrast` / `saturation` | Leave at defaults | Every manual tweak is one more thing to reproduce exactly at dataset-capture time. |

- **Freeze the firmware after capturing references.** If you re-flash with
  different settings, the references no longer match what the camera produces
  and you must recapture. This is the single easiest way to invalidate a day's
  work.
- Confirm the stream opens in a browser at `http://<ip>:81/stream` before you
  start; a stream that only half-works produces "Waiting for camera stream…"
  mid-shoot.
- Mount it, *then* shoot. A reference set captured handheld and deployed on a
  bracket is a different image domain.

### 1b. USB webcam (candidate B)

| Setting | Use | Why |
|---|---|---|
| Resolution | **640×480**, same as the ESP32 | Do not hand the webcam a resolution advantage the ESP32 never had — you are comparing *cameras*, and a fair test keeps everything else equal. |
| **Autofocus** | **Disable if your model allows it** | A hunting autofocus produces sharp references and a blurred live crop (or the reverse) — a moving image domain. A fixed focus set at lane distance is strictly better here. |
| Auto white balance | **on**, and let it settle ~10 s before the first shot | Same reason as the ESP32; just give it time to stabilise. |
| Mount position | **The same bracket, same height, same angle** the ESP32 used | This is what makes the camera comparison mean anything. |

Find the device first:

```bash
ls /dev/video*
```

```bash
py -3 -c "import cv2; c=cv2.VideoCapture(0); ok,f=c.read(); print(ok, None if f is None else f.shape); c.release()"
```

If that prints `False` or the wrong camera (a laptop's built-in lid camera is
usually index `0`), try `--index 1`, then `2`.

---

## 2. What the capture tool enforces for you

`capture_references.py` walks a fixed **pose set** per product and, for each
frame, does two things before it will let you save:

1. **Crops to the product** with the *same* cropper the live path and
   `build_db.py` use (`ml/product_crop.py`) and **saves the crop, not the whole
   frame** — so a reference and a live crop share one framing domain. If the
   scene is ambiguous (two comparable items), the product is too small, or the
   frame is blank, it shows **NO CROP** and refuses to save — the same refusal
   `build_db.py` makes, caught at capture time instead of poisoning the DB later.
2. Runs the **VIEW OK / VIEW POOR** indicator on that crop — the *same*
   usable-view test the live verifier uses (`ml/visibility.py`) — so you only
   ever save crops the system can actually judge.

The crop box is drawn live (green = will save, orange = won't). It won't let you
finish a product with too few photos (`MIN_PHOTOS = 5`).

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

## 3. Framing & lighting

- **Fill ~60–80% of the frame** with the product. Too small = the cropper reports
  `TOO_SMALL` and won't save; too large = edges clipped before the crop can pad
  them. The tool stores the **cropped product**, so present one clear item, well
  inside the frame.
- **Even, diffuse light.** Avoid a single hard lamp — glare blows out printing
  and kills the texture the visibility test and embedding rely on.
- **Plain, contrasting surface** behind the item (the deployment surface is
  ideal). Busy backgrounds leak into the crop.
- **Hold steady** — motion blur flattens texture and reads as VIEW POOR. This
  matters *more* on the ESP32-CAM, whose longer effective exposure smears motion
  the webcam would freeze.
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

Include **at least one** such product in the set. Pale, low-texture items are
where a weak camera fails first, so they are the most informative cases in the
whole bake-off.

---

## 4. Same-weight pairs (the attack you're defending against)

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

> Prepare **at least 3 such pairs**. These are the cases that produce the FAR
> number in the bake-off, and FAR is what picks the camera — a swap accepted as
> MATCH is a theft nobody notices.

---

## 5. Build the database — one per camera

After capturing, from the project root:

```bash
py -3 build_db.py --references references_esp32  --out embedding_db_esp32.pkl
py -3 build_db.py --references references_webcam --out embedding_db_webcam.pkl
```

*(After the bake-off, when one camera has won and its set is the only one left,
plain `py -3 build_db.py` uses the defaults `references/` → `embedding_db.pkl`.)*

This writes a `.pkl` containing, **per photo**, both the appearance embedding
*and* a paired colour histogram (the `"colours"` block), each computed on the
**cropped** product so references and live crops match. A photo the cropper can't
resolve is reported `REJECT … (AMBIGUOUS / TOO_SMALL / EMPTY)` and skipped rather
than stored mis-framed. Re-run it **every time** you add/remove photos or
products. Confirm the tail line reports the product count,
`[backend onnx-mbv2-1280]`, **and** `colour v2`.

> The colour fingerprint is **format-versioned**. If the DB's colour format is older than
> the code expects, the verifier prints `[verifier] Colour references are format …` and
> **disables colour** — MATCH becomes unreachable (SUSPECT at best, the safe direction) —
> until you rebuild. So after any code update that changes the colour format, re-run
> `build_db.py` **for both cameras**.

> The DB is also **stamped with the embedding backend** (`onnx` vs `tflite`), and the
> matcher refuses a mismatched stamp. If you change `EMBEDDING_BACKEND` in
> `ml/config.py`, rebuild **both** databases — otherwise tests 1 and 3 of the bake-off
> are scored by two different models and the comparison is void.

---

## 6. Sanity-check before the review

1. `py -3 test_verify.py` → **ALL CHECKS PASSED** (logic intact; 131 checks at
   time of writing). Runs fully offline — no camera, no API key.
2. `py -3 verify_demo.py` with the DB present:
   - Scan a product, carry it left→right into the cart-entry box, press `W` →
     **MATCH**.
   - Scan A, carry same-weight B → **SUSPECT / MISMATCH**.
   - Cover the item with your hand mid-transit → **RETRY** (broken custody).
   - Scan again mid-transit → old transaction **RETRY**, new one starts.
3. With **no** database present, the demo still starts and every scan
   resolves **UNAVAILABLE** — never a silent accept.

If step 2 gives **MISMATCH on a genuine item**, suspect the reference set before
you suspect the thresholds: wrong camera, moved mount, or changed ESP32 firmware
since capture are all far more likely than a bad constant in `ml/config.py`.

---

## 7. Capturing for BOTH cameras: the fairness rules

The bake-off compares two cameras on two datasets that **cannot** be the same
physical transactions — you can't shoot one instant from one mount point with two
cameras. So the two sessions must be made as alike as possible by hand, or the
"camera verdict" measures your shooting conditions instead of the hardware.

Do all of this in **one sitting**:

- [ ] **Same day, same lighting.** Not morning ESP32 and evening webcam.
- [ ] **Same products**, in the same order, including the same same-weight pairs.
- [ ] **Same mount position** — swap the module on one bracket; don't move the bracket.
- [ ] **Same handling** — same hand, same speed, same path across the frame.
- [ ] **Same number of photos per product**, and the same poses.
- [ ] **Same resolution** (640×480 both) — don't hand either camera an advantage.
- [ ] **Don't re-flash the ESP32** between its reference shoot and its dataset capture.

Then keep the outputs strictly separate:

```
references_esp32/   → embedding_db_esp32.pkl   → datasets/esp32/
references_webcam/  → embedding_db_webcam.pkl  → datasets/webcam/
```

> **Cross-contamination is the one mistake this SOP exists to prevent.** Scoring
> `datasets/esp32/` against `embedding_db_webcam.pkl` produces plausible-looking
> numbers that are pure domain gap. `run_bakeoff.py` takes the dataset/DB pairing
> from *your* flags and cannot detect the swap, so the pairing is on you.

The full step-by-step procedure — capture, build, score, and how to read the
resulting table — is in **[DEPLOYMENT.md §6](DEPLOYMENT.md)**. This SOP covers
only the photography.

---

## 8. Running on the 2 GB Raspberry Pi (memory & latency)

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

> The webcam is a USB device on the Pi and costs a port and some bus bandwidth;
> the ESP32-CAM costs WiFi instead. Neither meaningfully changes the RAM budget
> above — this decision is about **image quality**, not memory.

---

## 9. Hardware bring-up checklist

Do these in order. Items marked **(×2)** happen once per candidate camera while
the bake-off is open.

- [ ] **(×2)** Camera streaming and **mounted**: ESP32-CAM reachable at
      `http://<ip>:81/stream`, or webcam found at a known `--index`.
- [ ] **(×2)** Camera settings fixed per §1, and **not changed afterwards**.
- [ ] Confirm `SCANNER_REGION` / `CART_ENTRY_REGION` match where items actually
      enter and land in the mounted camera's view (they're frame fractions;
      adjust to the framing). Re-check after swapping modules — the two lenses
      have different fields of view even on the same bracket.
- [ ] Barcode scanner (USB-HID) — replace `MockBarcodeSource` with a real `poll()`
      returning a `ScanEvent(sku, txn_id, ts)`; supply your backend's order/line id as
      `txn_id` so verdicts correlate. Seam is in `ml/events.py` (contract: DEPLOYMENT §8a).
- [ ] Arduino load cell over serial — replace `MockWeightSource` so `poll()` emits
      `CHANGING` then `SETTLED` (optionally tagged with the same `txn_id`). Seam is in
      `ml/events.py` (contract: DEPLOYMENT §8a).
- [ ] **(×2)** Capture references through that camera (§0–§4), build its database
      (§5), and run the checks in §6 on real products.
- [ ] **(×2)** Capture a labelled dataset (`capture_dataset.py`) — DEPLOYMENT §6.3/§6.4.
- [ ] Run `run_bakeoff.py`, pick the winner, and collapse to one camera —
      DEPLOYMENT §6.6–§6.8.
