# NXTCart-Cam — Pi + ESP32-CAM Deployment & Integration Guide

Everything you need to run the camera-verification module on the Raspberry Pi with
the ESP32-CAM, what to copy, what to delete, how to test, and how to wire it into
the cart backend so it makes a product decision.

> This is the **hardware/deployment** companion to [`REFERENCE_SOP.md`](REFERENCE_SOP.md)
> (how to shoot reference photos) and [`ARCHITECTURE.md`](ARCHITECTURE.md) (why it's
> built this way). Read those for the *why*; this file is the *how*.

---

## 0. Mental model — what runs where

```
 ┌──────────────┐   MJPEG over WiFi     ┌───────────────────────────────┐
 │  ESP32-CAM   │ ───────────────────▶  │        Raspberry Pi (2 GB)     │
 │ (streams     │  http://IP:81/stream  │                                │
 │  video only) │                       │  THIS MODULE (Python):         │
 └──────────────┘                       │   frame_source → detector →    │
                                        │   item_follower → verifier →   │
 ┌──────────────┐   USB-HID (types)     │   custody  ─────────────▶ VERDICT
 │ Barcode gun  │ ───────────────────▶  │                                │
 └──────────────┘                       │  + your cart backend / display │
 ┌──────────────┐   serial "W:1234\n"   │  + payment gateway             │
 │ Arduino+cell │ ───────────────────▶  │                                │
 └──────────────┘                       └───────────────────────────────┘
```

- **The ESP32-CAM is *only a camera.*** It runs its own firmware and serves an MJPEG
  stream. This module never runs *on* the ESP32 — it runs on the Pi and **pulls** the
  ESP32's stream over WiFi. There is nothing to "load onto" the ESP32 from this repo.
- **The Pi runs all the Python.** It consumes the camera stream, the barcode scans,
  and the Arduino's settled-weight events, and produces one verdict per transaction.
- **The barcode and the load cell are inputs you feed in** through two tiny driver
  seams (§8). Tonight they're mocks; on the Pi you replace them with the real USB /
  serial readers.

---

## 1. Reality check on "saving memory" (read this before deleting anything)

Your instinct — *don't waste Pi memory* — is right, but the biggest lever is **not**
deleting `.py` files. Here is what actually costs **runtime RAM** vs. what only costs
**disk space**:

| Lever | Saves RAM at runtime? | Saves disk? | Notes |
|---|---|---|---|
| Choosing the lighter model backend | **Yes (~10 MB)** | Yes (3.5 vs 13.6 MB) | ONNX float ≈ 14 MB in RAM; TFLite quant ≈ 3.5 MB. But ONNX is ~250× faster — see §7. |
| Dropping `ai-edge-litert` from deps (ONNX-only) | **Yes (large)** | Yes | It's a heavy package; only needed for the TFLite fallback. |
| Bounded crop buffer / newest-frame-only source | **Yes (already done)** | — | Built in: peak ≈ `VERIFY_BURST_FRAMES × 224×224×3` ≈ a few MB. |
| Deleting unused `.py` modules | **No** | Tiny (~160 KB) | A module that is never imported uses **zero** runtime RAM. Delete them for *cleanliness*, not for RAM. |
| Deleting `.md` docs | **No** | Small (~135 KB) | Docs are never loaded at runtime. Pure disk. |

**Bottom line:** the module is already RAM-bounded by design. The one real RAM decision
is the **model backend** (§7). Deleting files keeps the Pi checkout clean and the
transfer small — worth doing — but don't expect it to move the RAM needle.

---

## 2. What to COPY to the Pi (the keep-set)

Copy the project folder but include **only** these. Everything here is either imported
at runtime or is a tool/data you need.

**Runtime package — required (`ml/`):**

```
ml/__init__.py
ml/config.py               # all tuning knobs live here
ml/camera.py               # webcam grabber (WebcamSource wraps it; harmless to keep)
ml/frame_source.py         # webcam + ESP32 MJPEG source
ml/detector.py             # background-subtraction blob detector
ml/events.py               # barcode + weight seams (mock now, real driver later)
ml/item_follower.py        # single-target lock + follow
ml/visibility.py           # usable-view test (texture/edge, not colour)
ml/verifier.py             # MATCH/SUSPECT/MISMATCH/RETRY/UNAVAILABLE
ml/custody.py              # transaction gating → VerdictResult
ml/recognizer.py           # EmbeddingRecognizer (appearance channel)
ml/matcher.py              # loads embedding_db.pkl, cosine, backend-stamp guard
ml/embedding_extractor.py  # runs the model (ONNX via cv2.dnn, or TFLite fallback)
```

**Model file — keep ONE (see §7):**

```
ml/mobilenet_v2.onnx          # 13.6 MB — the fast path, matches the current DB
ml/mobilenet_v2_quant.tflite  #  3.5 MB — the fallback; keep only if using TFLite
```

**Entry points, data, and tooling — required:**

```
verify_demo.py             # the runnable two-pane demo / smoke test
build_db.py                # (re)builds embedding_db.pkl from references/
capture_references.py      # guided reference-photo capture on the ESP32-CAM
test_verify.py             # headless logic test — run this first on the Pi
embedding_db.pkl           # 107 KB — the reference database (rebuild after capture)
references/                # 1.1 MB — your reference photos (rebuild source)
requirements.txt
REFERENCE_SOP.md           # capture procedure (needed when you shoot on the Pi)
DEPLOYMENT.md              # this file
```

That's the whole footprint: **source ≈ 0.2 MB, DB + references ≈ 1.2 MB, one model
3.5–13.6 MB.** Trivial for an SD card; the RAM story is §1/§7.

---

## 3. What to DELETE / not copy (dead weight)

None of these are imported by the keep-set (verified — the only mentions are in
comments). Safe to remove for a clean Pi checkout:

**Dead modules (superseded by the verification pipeline):**
```
ml/identity_tracker.py     # 49 KB
ml/zone_tracker.py         # 25 KB
ml/track.py                # 22 KB
ml/multi_frame_vote.py     #  7 KB
ml/cart_state.py           #  4 KB
```

**Old entry points (replaced by verify_demo.py):**
```
demo.py                    # 10 KB
live_cart_demo.py          # 13 KB
test_scripted.py           # 27 KB
```

**Scratch / generated:**
```
demo_out.txt               # empty
scripts/*.txt              # scratch notes
__pycache__/               # both ./__pycache__ and ./ml/__pycache__ (regenerated)
```

**Optional (disk only — safe to drop on the Pi, keep in git):** the large design docs
`ARCHITECTURE.md` (46 KB), `BUILD_PLAN.md` (30 KB), `CONTEXT_SNAPSHOT.md` (42 KB),
`IDENTITY_TRACKING.md` (17 KB). Keep `README.md`.

One-liner to prune a copied checkout on the Pi (run from the project root — **check
the list first**):

```bash
rm -f ml/identity_tracker.py ml/zone_tracker.py ml/track.py ml/multi_frame_vote.py ml/cart_state.py demo.py live_cart_demo.py test_scripted.py demo_out.txt
rm -rf __pycache__ ml/__pycache__ scripts
```

> Don't delete `ml/camera.py` even if you only use the ESP32-CAM — `verify_demo.py`
> can still fall back to `CAMERA_SOURCE="webcam"` for bench testing, and it's tiny.

---

## 4. Install on the Pi

Python 3.11+ on Raspberry Pi OS (64-bit recommended). From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Dependency choice tied to your backend (§7):**

- **ONNX (recommended default):** the fast path runs through **OpenCV's `cv2.dnn`**, not
  `onnxruntime`. So `opencv-python` + `numpy` + `requests` is all you need. You can
  **remove `ai-edge-litert` from `requirements.txt`** entirely — it's only for the
  TFLite fallback, and it's a heavy package. That's the single biggest install-size and
  import-RAM saving on the Pi.
- **TFLite fallback:** keep `ai-edge-litert` in `requirements.txt`.

> On some Pis `pip install opencv-python` pulls a large wheel or wants to build. If it
> struggles, `sudo apt install python3-opencv` gives you the system OpenCV instead
> (then create the venv with `--system-site-packages`). Either provides `cv2.dnn`.

Verify OpenCV can read the model at all:

```bash
python3 -c "import cv2; n=cv2.dnn.readNetFromONNX('ml/mobilenet_v2.onnx'); print('cv2.dnn OK')"
```

---

## 5. Point the Pi at the ESP32-CAM

### 5a. On the ESP32-CAM (one-time, done with Arduino IDE — not from this repo)
Flash it with a streaming sketch (the stock **`CameraWebServer`** example works). It
serves MJPEG at **`http://<ESP32-IP>:81/stream`**. Two network modes:

- **AP mode** (ESP32 is its own access point): the Pi joins the ESP32's WiFi; the
  stream is at `http://192.168.4.1:81/stream` — this is the repo default.
- **Station mode** (ESP32 joins your WiFi/router): read the IP it prints on the serial
  monitor at boot, e.g. `http://192.168.1.57:81/stream`.

Confirm the stream is alive from the Pi before touching Python:

```bash
curl -sI http://192.168.4.1:81/stream    # expect HTTP 200, content-type multipart/x-mixed-replace
```

### 5b. In `ml/config.py`
```python
CAMERA_SOURCE   = "mjpeg"                              # was "webcam" for the laptop
ESP32_STREAM_URL = "http://192.168.4.1:81/stream"      # match your ESP32's mode/IP
```

Then set the **regions** to match where items actually appear in the ESP32's mounted
view (they're fractions of the frame `(x0, y0, x1, y1)`):

```python
SCANNER_REGION     = (0.00, 0.00, 0.45, 1.00)   # left band: where a scanned item enters
CART_ENTRY_REGION  = (0.55, 0.00, 1.00, 1.00)   # right band: the cart mouth
```

The camera is mounted **opposite the scanner**, so items travel across the frame. Run
the demo once (§6) and watch the on-screen `scanner` / `cart entry` boxes — nudge these
fractions until an item genuinely starts in the scanner box and ends in the cart box.

The MJPEG source **auto-reconnects** on WiFi drops (it won't die on the first hiccup),
so a flaky link self-heals; the demo shows "Waiting for camera stream…" while it retries.

---

## 6. Capture references, build the DB, and test — step by step

Do these **in order** on the Pi, with the ESP32-CAM mounted where it will actually run.

**Step 1 — logic smoke test (no camera, no model needed):**
```bash
python3 test_verify.py          # expect: ALL CHECKS PASSED
```
If this fails, stop — the code didn't copy correctly. Nothing else will work.

**Step 2 — capture references through the ESP32-CAM** (this is the accuracy step;
see [`REFERENCE_SOP.md`](REFERENCE_SOP.md) for poses/lighting):
```bash
python3 capture_references.py   # walks the pose set, shows VIEW OK / VIEW POOR
```
Shoot **on the deployment camera** so live crops and references share an image domain.
Include your deliberate **same-weight pairs** (the attack you're defending).

**Step 3 — build the database:**
```bash
python3 build_db.py             # writes embedding_db.pkl
```
Confirm the tail line reports the product count, the backend stamp
(`[backend onnx-mbv2-1280]` for ONNX) **and** the colour format (`colour v2`). Each photo
is cropped to the product first (the *same* crop the live path applies); a reference that
can't be cropped confidently is reported `REJECT … (AMBIGUOUS / TOO_SMALL / EMPTY)` and
skipped, so a mis-framed photo never poisons a SKU. **Re-run this every time** you
add/remove photos, **change the backend** (§7), **or upgrade the colour-fingerprint
format.** The DB carries a colour-format version and the verifier **disables colour on a
stale stamp** — which makes `MATCH` unreachable (`SUSPECT` at best, the safe direction) —
until you rebuild, so an out-of-date DB fails safe rather than silently mis-scoring.

**Step 4 — end-to-end demo (the real smoke test):**
```bash
python3 verify_demo.py
```
Controls: **S** = scan next SKU, **W** = weight change (auto-settles), **R** = reset,
**Q** = quit. Walk these cases in front of the ESP32-CAM:

| Do this | Expect |
|---|---|
| Scan A, carry **A** left→right into the cart box, press **W** | **MATCH** |
| Scan A, carry a **different same-weight item** | **SUSPECT** (colour off) or **MISMATCH** (shape off) |
| Cover the item with your hand mid-transit | **RETRY** (broken custody) |
| Scan again mid-transit | old txn **RETRY**, new one starts |
| Delete/rename `embedding_db.pkl`, scan anything | **UNAVAILABLE** (never a silent accept) |

**Step 5 — measure on the Pi.** The per-verdict latency printed is real *on this Pi*
now (the laptop figure was a target). If it's too slow or RAM is tight, tune in
`ml/config.py`: lower `VERIFY_BURST_FRAMES` (fewer crops → less RAM + faster), or adjust
`VERIFY_PASS_FRACTION`. Re-run Step 4 after changes.

---

## 7. The model / backend decision (the one real RAM–speed trade)

`EMBEDDING_BACKEND` in `ml/config.py` controls this. `"auto"` (the default) **tries
ONNX first, falls back to TFLite**:

| Backend | How it runs | Speed (measured off-Pi) | RAM | DB stamp it needs |
|---|---|---|---|---|
| **ONNX** (`mobilenet_v2.onnx`, 13.6 MB) | OpenCV `cv2.dnn` — **no extra package** | ~6.5 ms/crop | ~14 MB | `onnx-mbv2-1280` |
| **TFLite** (`mobilenet_v2_quant.tflite`, 3.5 MB) | `ai-edge-litert` | ~1.6 s/crop* | ~3.5 MB | `tflite-mbv2quant-1280` |

\* The 1.6 s figure is from the **Windows** dev box, where the XNNPACK delegate had to be
disabled (it segfaulted). **On the Pi (ARM Linux) TFLite may be much faster** — this is
one thing worth measuring yourself. But at the Windows speed, ~1.6 s × several crops =
several seconds per verdict = unusable for a live cart.

**Recommendation:**

- **Default to ONNX.** It's the fast path, needs no extra package (runs on the OpenCV
  you already installed), and **your current `embedding_db.pkl` is already stamped for
  it** — nothing to rebuild. Keep `ml/mobilenet_v2.onnx`; you may **delete
  `ml/mobilenet_v2_quant.tflite`** and drop `ai-edge-litert` from `requirements.txt`.
  For safety pin it explicitly:
  ```python
  EMBEDDING_BACKEND = "onnx"     # in ml/config.py — fail loudly if ONNX won't load
  ```
- **Only switch to TFLite** if ONNX won't load on your Pi *and* you measure TFLite fast
  enough there. If you do:
  1. keep `ml/mobilenet_v2_quant.tflite` and `ai-edge-litert`,
  2. set `EMBEDDING_BACKEND = "tflite"`,
  3. **rebuild the DB** — `python3 build_db.py` — so it's re-stamped
     `tflite-mbv2quant-1280`. The matcher **refuses a mismatched-backend DB** (the two
     models produce numerically incompatible vectors), so skipping this makes the demo
     error out on load. That guard is intentional.

> The DB stamp is the safety interlock: it guarantees you never score live crops from
> one model against references embedded by the other.

---

## 8. Integrate into the cart backend (make the product decision)

The whole module reduces to **one object and one call**. You feed it frames; it hands
you a verdict when — and only when — a transaction completes.

### 8a. Wire the real barcode + weight drivers
Replace the two mocks with real readers by implementing the same tiny protocols from
`ml/events.py`. Nothing else changes.

**Barcode** — implement `poll() -> Optional[ScanEvent]` (return a freshly scanned item
once, as a `ScanEvent(sku, txn_id, ts)`). The `txn_id` is the **contract with your
backend**: pass the backend's own transaction / order-line id here and it is stamped onto
every `VerdictResult` (§8c), so a camera verdict can be correlated to — and rejected
against — the exact scan. If you have no id to supply, use any unique string (a counter,
a UUID); do **not** reuse one across scans.
```python
from ml.events import ScanEvent
import time

class UsbHidBarcodeSource:
    """USB-HID 'keyboard wedge' scanner: it types the digits + Enter."""
    def __init__(self):
        self._buf = ""
        self._pending = None            # a ScanEvent, or None
    def feed_key(self, ch):             # call from your keyboard/evdev reader
        if ch == "\n":
            sku = self._to_sku(self._buf)          # map raw digits → your SKU
            self._buf = ""
            self._pending = ScanEvent(sku=sku,
                                      txn_id=self._backend_txn_id(),  # your order id
                                      ts=time.monotonic())
        else:
            self._buf += ch
    def poll(self):
        evt, self._pending = self._pending, None
        return evt
```

**Weight** — implement `poll() -> Optional[WeightEvent]`. Custody only acts on the
`SETTLED` phase, using `evt.delta` (grams added). Read the Arduino serial line and emit
`CHANGING` while it moves, then `SETTLED` once it's still:
```python
from ml.events import WeightEvent, WeightPhase
import time, serial   # pyserial

class ArduinoWeightSource:
    def __init__(self, port="/dev/ttyUSB0", baud=115200):
        self._ser = serial.Serial(port, baud, timeout=0)
        self._last_stable = None
        self._queue = []
    def _read_grams(self):
        line = self._ser.readline().decode(errors="ignore").strip()
        # your Arduino format, e.g. "W:1234"
        return float(line[2:]) if line.startswith("W:") else None
    def poll(self):
        g = self._read_grams()
        if g is not None:
            # ...your change/settle detection here; when a change finishes:...
            delta = g - (self._last_stable or g)
            if abs(delta) > 5.0:       # settled with a real change
                self._last_stable = g
                # Pass the OPEN transaction's id here (see note) to bind the settle:
                self._queue.append(WeightEvent(WeightPhase.SETTLED, g, delta,
                                               time.monotonic(), txn_id=None))
        return self._queue.pop(0) if self._queue else None
```
> If your Arduino already decides "settled" and sends only the final delta, just emit a
> single `WeightPhase.SETTLED` event when that message arrives — even simpler.
>
> **Binding weight to the scan (optional, recommended when items are handled quickly
> back-to-back):** `WeightEvent` takes an optional `txn_id` (and `ts`). Tag the settle
> with the same id as the scan and custody will **drop** a settle that belongs to a
> *different* transaction, or one time-stamped **before** the current scan opened — so a
> late settle from the previous item can never complete this one. Leave `txn_id=None` and
> any settle binds to the open transaction (fine when items are added strictly one at a
> time).

### 8b. The per-frame loop (this is the entire integration surface)
```python
from ml.config import CAMERA_SOURCE
from ml.frame_source import make_frame_source
from ml.detector import BackgroundSubtractorDetector
from ml.recognizer import EmbeddingRecognizer
from ml.verifier import ProductVerifier, Verdict, load_colour_db
from ml.custody import CustodyController

# --- build once at startup ---
recog     = EmbeddingRecognizer()                 # loads model + embedding_db.pkl
verifier  = ProductVerifier(recog, appearance_db=recog.db, colour_db=load_colour_db())
detector  = BackgroundSubtractorDetector()
barcode   = UsbHidBarcodeSource()                 # your real driver
weight    = ArduinoWeightSource("/dev/ttyUSB0")   # your real driver
source    = make_frame_source(CAMERA_SOURCE, width=640, height=480)
controller = CustodyController(detector, verifier, barcode, weight, frame_size=(640, 480))

# --- per frame ---
while running:
    ok, frame, meta = source.read()
    if not ok:
        if not getattr(source, "stopped", True):   # transient WiFi drop → keep going
            continue
        break

    result = controller.process(frame, meta)        # ← feed barcode+weight+frame in
    if result is not None:                           # a transaction just completed
        cart_decision(result)                        # ← your backend, see 8c

    # (optional, for your display) live status without waiting for a verdict:
    #   controller.expected_sku, controller.follow_status,
    #   controller.reached_cart, controller.weight_settled
```
`process()` returns `None` on frames that don't complete a transaction, and a
`VerdictResult` exactly once when both proofs (reached-cart **and** weight-settled) are
in — or when it must bail (timeout, broken follow, second scan). Call
`controller.reset()` to abandon an in-flight transaction (e.g. operator cancel).

### 8c. Map the verdict to a cart action
`VerdictResult` fields: `.verdict`, `.appearance_score`, `.colour_score`,
`.appearance_pass_frac`, `.colour_pass_frac`, `.joint_pass_frac` (fraction of crops that
passed appearance **and** colour *on the same crop* — what `MATCH` is gated on),
`.usable_crops`, `.reason`, `.expected_sku`, `.txn_id` (the scan's transaction id, echoed
from §8a), `.weight_delta` (grams the scale settled by, for your own
expected-weight-for-SKU check), and the convenience `.accepted` (True **only** for
`MATCH`).

```python
def cart_decision(r):
    # r.txn_id ties this verdict to the exact scan (§8a). Reject a verdict whose
    # id you don't recognise or have already closed before acting on it.
    if r.verdict == Verdict.MATCH:
        add_to_cart(r.expected_sku)          # camera agrees with the barcode → accept
    elif r.verdict == Verdict.SUSPECT:
        flag_for_review(r)                   # shape ok, COLOUR wrong — the same-weight swap
    elif r.verdict == Verdict.MISMATCH:
        reject(r)                            # appearance wrong — not the scanned product
    elif r.verdict == Verdict.RETRY:
        ask_rescan(r.reason)                 # custody broken/timeout — re-present the item
    elif r.verdict == Verdict.UNAVAILABLE:
        # No reference for this SKU → the camera CANNOT judge this item at all.
        # Do NOT fall back to weight-only: a same-weight swap is invisible to weight,
        # so weight-only acceptance is exactly the hole the camera exists to close.
        # Block / hold for manual review until a reference is captured for this SKU.
        block_for_manual_review(r)
```

**How this fuses with your other sensors:** the camera answers exactly one question —
*"is the thing that entered the cart the SKU the barcode said?"* Weight already
confirmed *something* of the right mass was added; the camera is the vote that catches
the **same-weight substitution** weight physically cannot see. So a safe fusion rule is:

- **accept** the SKU to the cart only if weight agrees **and** the camera is `MATCH`;
- **hold / alert** on `SUSPECT` or `MISMATCH` even when weight is happy (that's the
  attack firing);
- treat `RETRY` as "not done yet — re-present";
- treat `UNAVAILABLE` as **block / manual review — never weight-only.** With no reference
  the camera abstains, and weight alone cannot see a same-weight swap, so accepting on
  weight would reopen the exact hole this module exists to close.

**Correlate by `txn_id`.** Every result carries the `.txn_id` you supplied at scan time
(§8a); match the verdict to your open order line by that id and **reject a verdict whose
id you don't recognise or have already closed.** The camera and the backend then share
one transaction identity end to end, and a verdict can never be applied to the wrong item.

Because `MATCH` is the *only* accepting verdict and no branch — `UNAVAILABLE` included —
defaults to acceptance, wiring it this way fails safe: a missing reference, a broken
follow, or a bad view never silently adds an item.

---

## 9. Quick troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Demo prints "No reference database" → all `UNAVAILABLE` | `embedding_db.pkl` missing or SKU not in it. Run `build_db.py`; confirm the backend stamp. |
| Load error mentioning backend mismatch | DB stamped for a different model than `EMBEDDING_BACKEND`. Rebuild the DB (§7). |
| Never reaches `MATCH`; best case is always `SUSPECT` | Colour is disabled. At startup you'll see `[verifier] Colour references are format …` — the DB's colour-format stamp is stale (or predates the colour block). Rebuild with `build_db.py` (§6 Step 3). |
| "Waiting for camera stream…" forever | ESP32 URL/mode wrong or Pi not on the ESP32's network. Check §5 `curl`. |
| Genuine matches score low | Domain mismatch — references not shot on the ESP32-CAM. Re-capture on the deployment camera (§6/`REFERENCE_SOP.md`). |
| Every transit ends `RETRY` (lost/ambiguous) | Regions don't match the mounted view, or lighting makes the follower drop the item. Adjust `SCANNER_REGION`/`CART_ENTRY_REGION`; check `VIS_*` floors. |
| Verdict too slow / RAM tight | Using TFLite where ONNX would do (§7), or `VERIFY_BURST_FRAMES` too high. Prefer ONNX; lower the burst. |
