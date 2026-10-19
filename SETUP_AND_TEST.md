# NXTCart-Cam — Set Up, Position the Camera, and Test It Today

Everything needed to test the **camera half** of the smart cart today, with a USB
webcam and real products, while the barcode scanner and load cell are still
dummy data. Read top to bottom the first time; after that, §3 is the daily loop.

> **Companions:** [`CART_INTEGRATION.md`](CART_INTEGRATION.md) wires this into the
> ROS 2 cart (`smart_cart_ws`). [`DEPLOYMENT.md`](DEPLOYMENT.md) covers the Pi and
> the camera bake-off. [`REFERENCE_SOP.md`](REFERENCE_SOP.md) is the photo
> procedure in more depth.

> **On this machine use `py -3`, not `python`** — bare `python` hits the Windows
> Store stub and fails.

---

## 0. What you are testing, and what you are not

The camera answers exactly one question:

> The barcode says this is SKU **X**. Is the item that just went into the cart
> actually **X**?

It exists for one attack that **weight physically cannot see**: scan a cheap
item, put in an expensive one of the **same weight**. The scale is satisfied;
only the camera can tell them apart.

**Today you can prove** (logic + your products, this laptop):

| Claim | How you prove it |
|---|---|
| Every verdict branch is correct | `py -3 test_verify.py` |
| The cart refuses a verified swap | `py -3 test_cart_logic.py` |
| A genuine item reads **MATCH** on your products | §3, case A |
| A same-weight swap reads **SUSPECT/MISMATCH** | §3, case B ← *the one that matters* |
| Cart and bill go up on add, down on removal | §3, cases C/D |

**Today you cannot prove:** Pi latency/RAM, ESP32-CAM image quality, Arduino
settle timing, or accuracy on products you have not photographed. Those need the
hardware.

---

## 1. One-time setup

```bash
cd /path/to/NXTCart-Cam
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Confirm the model loads and the logic is intact:

```bash
py -3 -c "import cv2; cv2.dnn.readNetFromONNX('ml/mobilenet_v2.onnx'); print('model OK')"
py -3 test_verify.py
```

`test_verify.py` must print **ALL CHECKS PASSED**. If it does not, stop — nothing
downstream will be meaningful.

Find your webcam:

```bash
py -3 cart_sim.py --list-cameras
```

A plugged-in USB webcam is usually **index 1** when a laptop also has a built-in
camera at index 0. Note the index you want; every tool takes `--index`.

---

## 2. Mount the camera (this decides your accuracy)

### 2.1 The geometry the code expects

The follower locks an item on the **scanner side** of the frame and follows it to
the **cart side**. Those are frame fractions in `ml/config.py`:

```python
SCANNER_REGION    = (0.00, 0.00, 0.45, 1.00)   # left 45%
CART_ENTRY_REGION = (0.55, 0.00, 1.00, 1.00)   # right 45%
```

So the item must **travel across the frame, left to right** (or right to left if
you swap the two). That is the single most important mounting constraint:

```
        camera  (mounted OPPOSITE the travel path, looking across it)
          |
          v
   ┌──────────────────────────────────────┐
   │  [scanner]  --- item travels --->  [cart mouth]  │
   │   left 45%        middle         right 45%        │
   └──────────────────────────────────────┘
```

**Mount the camera facing across the lane, not along it.** If it looks *down the
travel direction*, the item grows in place instead of crossing the frame, never
enters `CART_ENTRY_REGION`, and every transaction ends `RETRY`.

### 2.2 Position, angle, distance

| Setting | Target | Why |
|---|---|---|
| **Direction** | Perpendicular to the item's travel | The item must cross the frame (§2.1) |
| **Angle above the path** | **20–40° downward tilt** | Sees the top *and* a face. Flat-on (0°) hides the top; straight down (90°) hides the label and makes every box a rectangle |
| **Distance** | Item fills **25–60% of frame width** mid-travel | Below ~10% of frame area the cropper returns `TOO_SMALL`; too close clips the edges |
| **Height** | Just above the cart rim, looking slightly down | Keeps the shopper's torso out of the background |
| **Rigidity** | **Bolt it down** | Motion detection is background subtraction — a camera that shifts re-reads the whole scene as motion |

### 2.3 Background and lighting (cheapest accuracy wins)

- **Plain, matte, contrasting, and static** behind the travel path. A busy or
  moving background (people walking, a screen) leaks into crops and triggers
  `AMBIGUOUS`.
- **Diffuse, even light.** Two soft sources beat one bright lamp.
- **Never backlight the lane.** A window or lamp behind the item turns it into a
  dark silhouette, which destroys *both* the appearance and colour channels.
- **No specular hotspots.** Glare on glossy packaging blows out the print the
  appearance channel reads.
- **Keep the lens out of direct light.**

### 2.4 Lock the webcam's own auto-adjustments

This is the most commonly missed accuracy fix. Consumer webcams hunt:

- **Autofocus** hunting blurs crops mid-transit → `RETRY` or low appearance.
- **Auto-exposure / auto-white-balance** shifts colour between the reference
  photos and the live frame → the colour channel drifts and genuine items start
  reading `SUSPECT`.

Lock focus, exposure and white balance in your webcam's driver/utility (on
Windows: *Camera settings* → disable auto), **before** shooting references, and
leave them locked afterwards. If you cannot lock them, at least shoot references
and test in the **same lighting session**.

### 2.5 Resolution

Shoot and process at **640×480**. Crops are resized to 224×224 for the model, so
1080p buys no accuracy — it only costs RAM and latency on the 2 GB Pi. Use 720p
only if the item is unavoidably small in frame:

```bash
py -3 cart_sim.py --index 1 --width 1280 --height 720
```

### 2.6 Tune the regions to your actual mount

Run `cart_sim.py`, watch the drawn **SCANNER side** / **CART side** boxes, and
adjust the two fractions in `ml/config.py` until an item genuinely *starts* in
the scanner box and *ends* in the cart box. Mid-travel it should be in neither.

---

## 3. Photograph products, build the database, test

### 3.1 Shoot references — through the camera you will deploy

**Shoot on the mounted webcam, at the mount, in the deployment lighting.** A
reference photo encodes the *image domain* of the camera that took it. Phone
photos look sharper and score genuine items *lower*, because the live crop no
longer resembles them. This is the single biggest accuracy mistake.

```bash
py -3 capture_references.py --source webcam --index 1
```

For each product, the tool walks a pose set and shows a live indicator:

| Pose | Why it is in the set |
|---|---|
| `front` | the primary face |
| `back` | what the camera often sees as it is set down |
| `left` / `right` | narrow side profiles |
| `rotated` | ~45°, the natural in-hand angle |
| `hand_grip` | held as a shopper carries it, fingers partly occluding |
| `tilt` | top or bottom partly visible |

- `SPACE` saves (and advances); `N` skips a pose; `Q` finishes.
- It only lets you save when it can **crop the product confidently** *and* the
  crop is a **usable view** — the same tests the live path runs. `NO CROP` or
  `VIEW POOR` means fix the framing, not override it.
- Fill **60–80%** of the frame with one product on a plain surface.
- **5–8 photos per product**, spread across poses. More angles beats more
  duplicates of the front face.
- Photos land in `references/<product>/001.jpg …` — the existing layout, so the
  insertion workflow is unchanged.

**Shoot a deliberate same-weight pair.** Two products of similar size and weight
but different colour/packaging. That pair *is* the attack test in §3.3.

### 3.2 Build the database

```bash
py -3 build_db.py
```

Confirm the summary line reports your product count, `[backend onnx-mbv2-1280]`
and **`colour v2`**. Photos the cropper cannot resolve are printed as
`REJECT … (AMBIGUOUS / TOO_SMALL / EMPTY)` and skipped rather than poisoning a
SKU — a few rejects are normal; *mostly* rejects means re-read §2.3.

Re-run this **every time** you add or remove photos.

> If colour is stale or missing you will see
> `[verifier] Colour references are format …` at startup and **MATCH becomes
> unreachable** (SUSPECT at best — the safe direction). Rebuilding fixes it.

### 3.3 Test with real products

Optional: set per-product weights for the fake scale in `weights.json`, and
prices in `prices.json`. `gel` and `soap` ship at the **same 150 g** on purpose,
so they are a ready-made same-weight pair.

```bash
py -3 cart_sim.py --index 1
```

Controls: `1..9` scan that SKU · `W` scale settles (completes the add) ·
`X` remove the last added item · `E` a removal matching nothing ·
`R` reset transaction · `B` reset background · `Q` quit

Walk these four cases:

| # | Do this | Expect |
|---|---|---|
| **A** | Scan product **A**, carry **A** scanner→cart, press `W` | **MATCH**, cart +1, bill up |
| **B** | Scan product **A**, carry **same-weight B**, press `W` | **SUSPECT** or **MISMATCH**, cart unchanged ← *the attack* |
| **C** | Press `X` | item removed, cart and bill go down |
| **D** | Press `E` | `UNEXPECTED_REMOVAL` flag, cart unchanged |

Also worth provoking: cover the item with your hand mid-transit (**RETRY**),
scan again mid-transit (old transaction **RETRY**), and scan with no database
(**UNAVAILABLE** — never a silent accept).

**A and B both holding on your products, in your lighting, is the bar.** Until
then the thresholds are unproven guesses on your catalogue.

---

## 4. If the results are bad, tune in this order

Work top-down; the top two fix most problems and cost nothing.

1. **Re-shoot references on the deployment camera** (§3.1). Fixes most
   "genuine items score low".
2. **Fix lighting and lock auto-exposure/focus** (§2.3, §2.4).
3. **Re-aim and adjust the regions** (§2.6) if transits end `RETRY`.
4. **Add poses** for products that fail from particular angles.
5. **Only then touch thresholds** in `ml/config.py`:

| Knob | Default | Raise it to… | Lower it to… |
|---|---|---|---|
| `VERIFY_APPEARANCE_THRESHOLD` | `0.72` | reject more (fewer swaps pass) | accept more (fewer false rejects) |
| `VERIFY_COLOR_THRESHOLD` | `0.55` | demand closer colour | tolerate lighting drift |
| `VERIFY_PASS_FRACTION` | `0.50` | demand more agreeing views | accept on thinner evidence |
| `VERIFY_MIN_USABLE_FRAMES` | `3` | demand more clean views | verdicts on fewer views |
| `VERIFY_BURST_FRAMES` | `12` | more views scored (slower, more RAM) | faster, lighter on the Pi |

These three defaults are **seeded guesses, not measurements** — the config says so
itself. Change one at a time and re-run §3.3.

> **Never "fix" a failure by raising thresholds until swaps pass.** The honest
> failure directions are `SUSPECT` (flag) and `MISMATCH` (reject); a swap that
> reads `MATCH` is the one outcome that must never be tuned into existence.
> `DEPLOYMENT.md` §6 has the FAR/FRR bake-off for measuring this properly.

---

## 5. Daily loop, once it is set up

```bash
py -3 test_verify.py                       # logic still intact
py -3 capture_references.py --index 1      # add/replace product photos
py -3 build_db.py                          # rebuild after ANY photo change
py -3 cart_sim.py --index 1                # test on real products
```

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `python was not found` | Use `py -3` on this machine. |
| No camera found / black frames | Wrong `--index` (try `--list-cameras`), or Zoom/Teams/Camera holds the device. Close them. |
| Every transit ends `RETRY` | Item never reaches `CART_ENTRY_REGION`. Camera is aimed along the path, not across it (§2.1), or regions do not match the mount (§2.6). |
| `WAITING` forever, nothing locks | Item never appears in `SCANNER_REGION`, or the background model is stale — press `B` and hold still. |
| Status flips to `AMBIGUOUS` | Two things moving. Clear the background; move one item at a time. |
| `MERGED` | Item fused with your hand. Hold it by an edge, or grip less of it. |
| Best case is always `SUSPECT`, never `MATCH` | Colour is disabled (stale colour format). Re-run `build_db.py` (§3.2). |
| Every scan is `UNAVAILABLE` | No references for that SKU. Shoot them and rebuild. |
| Genuine items score low | Domain mismatch — references not shot on this camera (§3.1), or auto-exposure drift (§2.4). |
| Colour passes but appearance fails | Usually blur. Lock autofocus; add light. |
| Slow / laggy | Drop to 640×480; lower `VERIFY_BURST_FRAMES`. |

---

## 7. What changes when the hardware arrives

Nothing in the camera path. The two fakes are replaced at the seams they already
use (`ml/events.py` protocols; in ROS, the two dummy nodes):

| Today | Then |
|---|---|
| `1..9` keys / `dummy_scan_node` | USB-HID barcode gun → `qr_scanner_node` |
| `W`/`X` keys / `dummy_weight_node` | Arduino load cell → serial node |
| `--source webcam` | keep the webcam, or `--source mjpeg` for ESP32-CAM |

Switching to the ESP32-CAM means **re-shooting every reference** on it and
rebuilding — references are camera-specific (`DEPLOYMENT.md` §6).
[`CART_INTEGRATION.md`](CART_INTEGRATION.md) has the ROS 2 wiring.
