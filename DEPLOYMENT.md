# NXTCart-Cam — Deployment, Camera Bake-Off & Integration Guide

Everything you need to run the camera-verification module on the Raspberry Pi: what to
copy, what to delete, **how to choose the camera and the verifier by measurement**, and
how to wire it into the cart backend so it makes a product decision.

> This is the **hardware/deployment** companion to [`REFERENCE_SOP.md`](REFERENCE_SOP.md)
> (how to shoot reference photos) and [`ARCHITECTURE.md`](ARCHITECTURE.md) (why it's
> built this way). Read those for the *why*; this file is the *how*.

## The open question this guide now answers

Two things are **undecided**, and they are entangled:

1. **Which camera?** The **ESP32-CAM** is cheap, wireless and needs no host port — but
   its image quality is poor, and image quality is the *entire input* to this module. A
   **USB webcam** (the detachable one you already have) sees far more detail, at the cost
   of a cable to the Pi.
2. **Which verifier?** The **local** path (MobileNetV2 embedding + HSV colour) or an
   **AI vision model** called over an API.

**Both cameras are live candidates. We pick the one that measures better — not the one
that sounds better.** Neither question can be answered alone: a bad camera makes a good
verifier look useless, and a good camera can rescue a mediocre one. So §6 runs **all four
combinations** on labelled data and prints one table:

| Test | Camera | Verifier | What it costs to run |
|---|---|---|---|
| **1** | ESP32-CAM | local ML only, no AI | free, offline |
| **2** | ESP32-CAM | AI vision model | ~1¢ for the whole run |
| **3** | USB webcam | local ML only, no AI | free, offline |
| **4** | USB webcam | AI vision model | ~1¢ for the whole run |

The winner is decided on **FAR** (how often a swapped item is waved through), not on
"accuracy" — see §6.0. Everything needed to run all four already exists in the repo; §6
is the procedure, not a to-do list.

> **On this Windows machine use `py -3`, not `python`.** The Pi commands below use
> `python3`. Same scripts, different launcher.

---

## 0. Mental model — what runs where

```
 ┌──────────────┐   MJPEG over WiFi     ┌───────────────────────────────┐
 │  ESP32-CAM   │ ───────────────────▶  │        Raspberry Pi (2 GB)     │
 │  CANDIDATE A │  http://IP:81/stream  │                                │
 └──────────────┘                       │  THIS MODULE (Python):         │
 ┌──────────────┐   USB / UVC           │   frame_source → detector →    │
 │  USB webcam  │ ───────────────────▶  │   item_follower → verifier →   │
 │  CANDIDATE B │  /dev/video0          │   custody  ─────────────▶ VERDICT
 └──────────────┘                       │                                │
 ┌──────────────┐   USB-HID (types)     │  + your cart backend / display │
 │ Barcode gun  │ ───────────────────▶  │  + payment gateway             │
 └──────────────┘                       │                                │
 ┌──────────────┐   serial "W:1234\n"   │                                │
 │ Arduino+cell │ ───────────────────▶  │                                │
 └──────────────┘                       └───────────────────────────────┘
        ▲
        └─ exactly ONE of A or B ships. §6 decides which, from measurements.
```

- **Either camera is just a camera.** The ESP32-CAM runs its own firmware and serves an
  MJPEG stream; the webcam is a UVC device on `/dev/video0`. This module never runs *on*
  the ESP32 — it runs on the Pi and **pulls** the stream. There is nothing to "load onto"
  the ESP32 from this repo.
- **Nothing downstream knows which camera it is.** Both arrive through the same
  `FrameSource` seam (`ml/frame_source.py`), which stamps every frame with a monotonic
  `seq`. The detector, follower and verifier are identical either way — which is exactly
  what makes a fair bake-off possible.
- **The Pi runs all the Python.** It consumes the camera stream, the barcode scans, and
  the Arduino's settled-weight events, and produces one verdict per transaction.
- **The barcode and the load cell are inputs you feed in** through two tiny driver
  seams (§8). Today they're mocks; on the Pi you replace them with the real USB /
  serial readers.

### Trade-offs, before any measurement

| | ESP32-CAM | USB webcam |
|---|---|---|
| Image quality | **Poor** — small sensor, heavy JPEG, soft lens | **Good** — the reason it's a candidate |
| Mounting | Free — wireless, place it anywhere | Cable run to the Pi |
| Pi USB ports | None used | One used (barcode gun also wants one) |
| Failure mode | WiFi drops, stalls, reconnects | Effectively none once plugged in |
| Latency to first frame | WiFi RTT + decode | Near zero |
| Cost | ~₹400 | Already owned |

The ESP32-CAM wins on mounting; the webcam wins on the thing that actually feeds the
model. **That is why this is measured rather than argued.**

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
ml/camera.py               # webcam grabber (WebcamSource wraps it — REQUIRED if the
                           #   webcam wins the bake-off; keep it either way, it's tiny)
ml/frame_source.py         # webcam + ESP32 MJPEG source, behind one seam
ml/detector.py             # background-subtraction blob detector
ml/events.py               # barcode + weight seams (mock now, real driver later)
ml/item_follower.py        # single-target lock + follow
ml/visibility.py           # usable-view test (texture/edge, not colour)
ml/verifier.py             # MATCH/SUSPECT/MISMATCH/RETRY/UNAVAILABLE
ml/custody.py              # transaction gating → VerdictResult
ml/recognizer.py           # EmbeddingRecognizer (appearance channel)
ml/matcher.py              # loads the .pkl, cosine, backend-stamp guard
ml/embedding_extractor.py  # runs the model (ONNX via cv2.dnn, or TFLite fallback)
ml/backends.py             # VerificationBackend protocol + LocalBackend wrapper
ml/ai_backend.py           # VLMBackend — only needed if AI wins the bake-off
```

**Model file — keep ONE (see §7):**

```
ml/mobilenet_v2.onnx          # 13.6 MB — the fast path, matches the current DB
ml/mobilenet_v2_quant.tflite  #  3.5 MB — the fallback; keep only if using TFLite
```

**Entry points, data, and tooling — required:**

```
verify_demo.py             # the runnable two-pane demo / smoke test
build_db.py                # (re)builds a .pkl from a references dir  [--references --out]
capture_references.py      # guided reference-photo capture           [--source --out]
test_verify.py             # headless logic test — run this first on the Pi
requirements.txt
REFERENCE_SOP.md           # capture procedure (needed when you shoot on the Pi)
DEPLOYMENT.md              # this file
```

**Bake-off tooling — needed until the camera decision is made (§6), then optional:**

```
capture_dataset.py         # labelled G/X capture   [--source --url --index --db]
compare_backends.py        # local vs AI on one dataset          [--db --backends]
run_bakeoff.py             # all four tests, one ranked table
datasets/                  # the labelled transactions you capture
```

**Reference sets and databases — ONE PAIR PER CAMERA while the bake-off runs:**

```
references_esp32/     +  embedding_db_esp32.pkl
references_webcam/    +  embedding_db_webcam.pkl
```

> **Why two of everything.** A reference photo doesn't just record a product, it records
> that product *as seen by one camera* — sensor noise, white balance, lens softness and
> JPEG quality are baked in. Scoring ESP32 crops against webcam-built references measures
> the **gap between two cameras**, not the accuracy of either, and the table would blame
> the camera for a mistake made in setup. After the winner is chosen, keep only the
> winner's pair and rename them to plain `references/` + `embedding_db.pkl`.

That's the whole footprint: **source ≈ 0.25 MB, one DB + references ≈ 1.2 MB, one model
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

> **Don't delete `ml/camera.py`.** The USB webcam is a live candidate to *be* the
> deployment camera (§6), and `WebcamSource` wraps this module. Even if the ESP32-CAM
> wins, keep it for bench testing — it's tiny.

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

## 5. Connect the camera (either candidate)

Every tool in this repo takes `--source` on the command line, so **you never have to edit
`ml/config.py` to switch cameras.** That matters more than convenience: the bake-off runs
the same tools four times against different hardware, and a config edit forgotten between
runs produces a dataset silently captured on the wrong camera — which looks completely
normal on disk and invalidates every number downstream.

`ml/config.py` only supplies the **defaults** used when a flag is omitted.

### 5a. Candidate A — ESP32-CAM (`--source mjpeg`)

One-time, with the Arduino IDE (not from this repo): flash a streaming sketch — the stock
**`CameraWebServer`** example works. It serves MJPEG at **`http://<ESP32-IP>:81/stream`**.
Two network modes:

- **AP mode** (ESP32 is its own access point): the Pi joins the ESP32's WiFi; the
  stream is at `http://192.168.4.1:81/stream` — this is the repo default.
- **Station mode** (ESP32 joins your WiFi/router): read the IP it prints on the serial
  monitor at boot, e.g. `http://192.168.1.57:81/stream`.

Confirm the stream is alive **before touching Python**:

```bash
curl -sI http://192.168.4.1:81/stream
```

Expect `HTTP 200` and `content-type: multipart/x-mixed-replace`. Then point any tool at
it with `--source mjpeg --url http://192.168.4.1:81/stream`.

**Set the ESP32's own image settings before capturing anything.** They are firmware-side
and this repo cannot change them, but they materially affect the only input the model
gets. In the `CameraWebServer` sketch or its web UI:

| Setting | Use | Why |
|---|---|---|
| `framesize` | **VGA (640×480)** | Matches the 640×480 the tools resize to; larger just costs WiFi bandwidth and stalls |
| `quality` | **10–12** (lower = better) | JPEG blocking is a *colour-channel* confound, and colour is what catches a same-weight swap |
| `vflip` / `hmirror` | as mounted | Fix orientation **now** — references and live crops must agree |
| AWB / AEC | on | Leave auto unless the lane lighting is fixed |

Whatever you choose, **do not change it after capturing references.** A firmware setting
changed mid-bake-off silently moves the image domain and invalidates the run.

The MJPEG source **auto-reconnects** on WiFi drops (it won't die on the first hiccup),
so a flaky link self-heals; tools show "Waiting for camera stream…" while it retries.

### 5b. Candidate B — USB webcam (`--source webcam`)

Plug it in. Find its index:

```bash
ls /dev/video*
```

Usually `/dev/video0` → `--index 0`. If the Pi has another camera attached (or the webcam
exposes a metadata node), try `--index 1`. On Windows the indices are 0, 1, 2… in
enumeration order; there is no `/dev` to list, so just try them.

```bash
python3 -c "import cv2; c=cv2.VideoCapture(0); ok,f=c.read(); print(ok, None if f is None else f.shape); c.release()"
```

Expect `True (480, 640, 3)`. If `False`, try the next index.

- **Disable any autofocus hunting** if the webcam has it — a lens racking in and out
  mid-transit produces blurred crops the visibility gate then discards, which shows up as
  `RETRY`, not as a bad camera.
- **Mount it where the ESP32-CAM would go**, at the same height and angle. If the two
  cameras see the lane differently, §6 is comparing viewpoints, not sensors.

### 5c. Regions — do this for whichever camera you mount

Set the **regions** to match where items actually appear in that camera's mounted view
(fractions of the frame, `(x0, y0, x1, y1)`):

```python
SCANNER_REGION     = (0.00, 0.00, 0.45, 1.00)   # left band: where a scanned item enters
CART_ENTRY_REGION  = (0.55, 0.00, 1.00, 1.00)   # right band: the cart mouth
```

The camera is mounted **opposite the scanner**, so items travel across the frame. Run
`verify_demo.py` once and watch the on-screen `scanner` / `cart entry` boxes — nudge these
fractions until an item genuinely starts in the scanner box and ends in the cart box.

> **The two cameras may need different regions** if their fields of view differ. Check
> them separately, and re-check after any re-mount. Regions that don't match the view are
> the single most common cause of everything ending in `RETRY`.

---

## 6. The four-way camera bake-off — step by step

This is the section that **decides the hardware**. It runs four tests and ranks them:

| Test | Camera | Verifier | Command flavour |
|---|---|---|---|
| **1** | ESP32-CAM | local ML only | `--source mjpeg`, `--backends local` |
| **2** | ESP32-CAM | AI vision | `--source mjpeg`, `--backends ai` |
| **3** | USB webcam | local ML only | `--source webcam`, `--backends local` |
| **4** | USB webcam | AI vision | `--source webcam`, `--backends ai` |

**All the code exists.** Nothing below asks you to write anything.

---

### 6.0 First: the number that decides it

Do **not** rank these on "accuracy". This is a theft-prevention component, and the two
ways of being wrong cost wildly different amounts:

| Metric | What happened | What it costs |
|---|---|---|
| **FAR** — false accept | a **swap** was called `MATCH` | **the theft succeeds and nobody ever finds out** |
| **FRR** — false reject | a **genuine** item was called `MISMATCH`/`SUSPECT` | an honest shopper is stopped, staff called — expensive, but a human fixes it |
| **Retry rate** | either was called `RETRY` | pure friction; the shopper re-presents the item |

**A configuration with better headline accuracy but a worse FAR is the worse
configuration.** It is letting thefts through in order to avoid annoying people. So the
ranking is: **FAR first, then FRR, then retry rate**, and a tie goes to the local backend
because it is free and ~200× faster. That policy lives in `rank_cells()` in
`run_bakeoff.py` and is covered by `test_verify.py`.

`RETRY` is scored separately from both, deliberately: a backend that answers `RETRY` to
everything has a **perfect FAR** and is completely useless. Without its own column it
would look like the safest option on the table.

---

### 6.1 What you need before you start

**Products — this is the part people get wrong.**

- **8–12 real products** you'd actually stock.
- Among them, **at least 3 same-weight pairs**: two items of near-identical weight but
  different colour/appearance (two similar bottles, two similar cartons). *This is the
  entire attack.* A swap between a 200 g packet and a 2 kg bag proves nothing — the load
  cell already catches it. Only a same-weight swap tests the camera.
- Include **at least one low-saturation product** (white/beige carton, rice bag, clear
  bottle). These are the hardest for the colour channel and you want to know now.

**Hardware**

- ESP32-CAM, flashed and streaming (§5a), settings frozen.
- The USB webcam (§5b).
- A mount that puts **both cameras in the same position** — same height, same angle, same
  distance. If they see different things, §6 compares viewpoints, not sensors.

**For tests 2 and 4 only — an API key**

```bash
export OPENROUTER_API_KEY=sk-or-...
```

(Windows: `setx OPENROUTER_API_KEY sk-or-...`, then open a new shell.)

Get it from [openrouter.ai](https://openrouter.ai). One key reaches every vision model,
so you can try several without new accounts. **$10 is far more than this project will
ever use** — a 60-case run costs well under one cent. Start on a `:free` model to
validate the plumbing, then switch to `z-ai/glm-5.3-flash` for the real numbers.

No key? Tests 2 and 4 report `SKIPPED — no API key`. Tests 1 and 3 still run and still
answer the camera question for the local path. **They are never silently skipped**, and a
missing key can never produce a `MATCH` — every failure path in `ml/ai_backend.py` returns
`RETRY`, which `test_verify.py` checks in ten different ways.

**Budget the time.** Roughly 1 hour per camera for references + dataset. Do both **on the
same day, in the same light** (see 6.5).

---

### 6.2 Step 0 — prove the code is intact (2 minutes, no hardware)

```bash
py -3 test_verify.py
```

Expect **`ALL CHECKS PASSED`** (131 checks at time of writing). This runs fully offline — no camera, no
model, no API key, no network. If it fails, **stop**: nothing below will mean anything.

---

### 6.3 Phase A — ESP32-CAM: references, then dataset

Mount the ESP32-CAM in its final position and **don't move it until Phase A is done.**

**A1 — capture reference photos through the ESP32-CAM:**

```bash
py -3 capture_references.py --source mjpeg --url http://192.168.4.1:81/stream --out references_esp32
```

It walks a fixed pose set per product and shows a live **VIEW OK / VIEW POOR** indicator —
the same usable-view test the live verifier applies — so you can only save frames the
system can actually judge. Full procedure, poses and lighting:
[`REFERENCE_SOP.md`](REFERENCE_SOP.md).

Type each product name at the prompt; press ENTER on an empty name to finish.

**A2 — build the ESP32 database:**

```bash
py -3 build_db.py --references references_esp32 --out embedding_db_esp32.pkl
```

Confirm the tail line reports your product count, the backend stamp
(`[backend onnx-mbv2-1280]`) **and** `colour v2`. Photos the cropper can't resolve are
reported `REJECT … (AMBIGUOUS / TOO_SMALL / EMPTY)` and skipped rather than stored
mis-framed.

**A3 — capture the labelled ESP32 dataset:**

```bash
py -3 capture_dataset.py --name esp32 --source mjpeg --url http://192.168.4.1:81/stream --db embedding_db_esp32.pkl
```

For each transaction: press **S** to scan a SKU, carry the item across the frame into the
cart box, press **W** for the weight event — then **label what you actually did**:

| Key | Meaning |
|---|---|
| **G** | **genuine** — the item really was the scanned SKU |
| **X** | **swap** — you deliberately carried a *different* item |
| **D** | discard (fumbled run, mis-scan) |
| **R** | reset a stuck transaction |
| **Q** | quit |

**Target: ~30 genuine and ~30 swap.** Fewer than 20 total and the error rates are mostly
noise — the tool warns you when you quit under that.

**Vary the handling deliberately.** Different angles, speeds, hand positions, a few
awkward runs. A dataset of only clean presentations flatters every backend equally and
tells you nothing about the hard cases you actually care about.

Each transaction is written to `datasets/esp32/<timestamp>_<sku>_<label>/` as
full-resolution PNG crops plus a `meta.json` recording the label, the SKU **and which
camera shot it**. Crops are full-res and PNG on purpose: downscaling later is trivial,
upscaling is impossible, and JPEG artefacts are a colour-channel confound.

---

### 6.4 Phase B — USB webcam: references, then dataset

Now **swap the camera**, putting the webcam in the same position at the same height and
angle. Repeat everything with `--source webcam`:

**B1 — references:**

```bash
py -3 capture_references.py --source webcam --index 0 --out references_webcam
```

**B2 — database:**

```bash
py -3 build_db.py --references references_webcam --out embedding_db_webcam.pkl
```

**B3 — labelled dataset:**

```bash
py -3 capture_dataset.py --name webcam --source webcam --index 0 --db embedding_db_webcam.pkl
```

**Use the same products, the same swaps, and the same counts as Phase A.**

> **Why a second set of references at all?** Because a reference photo records the
> product *as seen by one camera* — sensor noise, white balance, lens softness and JPEG
> quality are baked in. If you score ESP32 crops against webcam-built references, genuine
> items fail for a reason that has nothing to do with the product, and the table blames
> the camera for a setup mistake. `ml/matcher.py` caches databases **by path** so both can
> be loaded in one process without one silently masquerading as the other.

---

### 6.5 Fairness rules — read before capturing, not after

Within one camera, tests 1-vs-2 and 3-vs-4 are **exact**: both backends score the
identical saved crops in the identical order, so any difference is purely the verifier.

Across cameras, 1-vs-3 and 2-vs-4 are **not exact**. You cannot shoot the same physical
instant with two cameras mounted in one place, so the two datasets are different
transactions of the same products. To keep that comparison as fair as it can be:

- [ ] **Same day, same lighting.** Don't shoot one at noon and one at night.
- [ ] **Same products and the same swap pairs**, in the same proportions.
- [ ] **Same counts** — ~30 genuine + ~30 swap each. Unequal sizes are flagged in the
      output as not directly comparable.
- [ ] **Same mount position**, height and angle.
- [ ] **Same handling style.** Don't get noticeably better at presenting items during the
      second session — capture them close together to limit that.
- [ ] **Don't change ESP32 firmware settings** (§5a) between references and dataset.

Treat a **small** cross-camera gap as noise. Only a **large, consistent** gap — the
webcam better on both backends, or worse on both — is real evidence about the camera.

---

### 6.6 Phase C — run all four tests

One command runs the whole matrix:

```bash
py -3 run_bakeoff.py --esp32-dataset esp32 --esp32-db embedding_db_esp32.pkl --webcam-dataset webcam --webcam-db embedding_db_webcam.pkl --price-per-m 0.075
```

It loads each dataset **once** and shares it between that camera's two tests — which is
what makes 1-vs-2 and 3-vs-4 exact rather than merely similar.

Useful variations:

```bash
py -3 run_bakeoff.py --esp32-dataset esp32 --esp32-db embedding_db_esp32.pkl
```
Only one camera captured so far. Tests 3 and 4 report `SKIPPED — no dataset` rather than
vanishing from the table.

```bash
py -3 run_bakeoff.py --esp32-dataset esp32 --esp32-db embedding_db_esp32.pkl --webcam-dataset webcam --webcam-db embedding_db_webcam.pkl --tests 1,3
```
Local-only (free, offline, no key) — answers the camera question on its own.

```bash
py -3 run_bakeoff.py ... --base-url http://localhost:11434/v1 --model minicpm-v4.6:1b
```
Point the AI tests at a local Ollama instead of the cloud. No key needed.

```bash
py -3 run_bakeoff.py ... --verbose
```
Print every case as it is scored, with `ok` / `xx` / `!!` marks — use this to find *which*
transactions are failing.

**To run one cell at a time**, `compare_backends.py` does a single dataset:

```bash
py -3 compare_backends.py --dataset esp32 --db embedding_db_esp32.pkl --backends local
```

It prints the full 5×5 confusion matrix and names every failing transaction — more detail
per cell than the four-way summary. Use `run_bakeoff.py` to decide, this to investigate.

---

### 6.7 Reading the table and making the call

The output has four parts:

**1. The metric table** — every test side by side, safety first.

**2. `BACKEND VERDICT` (exact)** — per camera, does AI beat local on the *same crops*?
It also reports whether they fail on the **same** cases or **different** ones:

- *Different cases* → a combined design wins: local runs every item, AI is called only to
  escalate `SUSPECT`. You get AI's catch rate at local's average latency.
- *Same cases* → escalation adds cost without adding safety. The hard cases are hard for
  both, and the fix is better references or better lighting, not a bigger model.

**3. `CAMERA VERDICT` (approximate)** — per backend, ESP32 vs webcam. Explicitly labelled
approximate, for the reasons in 6.5.

**4. `RECOMMENDATION`** — the ranked list and a named winner.

Then decide:

| What the table shows | What to do |
|---|---|
| ESP32 FAR is low and close to the webcam's | **Ship the ESP32-CAM.** Wireless mounting is worth real money; don't buy quality you don't need. |
| Webcam FAR is **much** lower on *both* backends | **Ship the webcam.** The image quality is doing genuine work. Budget a USB port and a cable run. |
| Local FAR is already near zero on the winning camera | **Don't ship AI at all.** It costs 100–1000× the latency to fix a problem you don't have. |
| AI clearly beats local, and they fail on *different* cases | Ship local as the fast path, **escalate `SUSPECT` to AI only**. Then fix the frame-loss hole first (§6.9). |
| AI clearly beats local, and they fail on the *same* cases | The problem is your references or your lighting. Re-shoot (`REFERENCE_SOP.md` §2) before buying anything. |
| Everything has a high retry rate | Not an accuracy problem. Check `SCANNER_REGION`/`CART_ENTRY_REGION` (§5c) and the `VIS_*` floors — the item is being lost in transit, not misjudged. |
| FAR is high everywhere | Thresholds, not hardware. `VERIFY_*` in `ml/config.py` are **seeded guesses** that have never been fitted to real data. Raise them and re-run — the dataset is saved, so re-scoring is free and instant. |

> **On dataset size.** Under ~20 cases, one misclassification moves a rate by several
> points and the tool says so. Treat small runs as directional. Before spending money on
> hardware, get to ~30 genuine + ~30 swap **per camera**.

---

### 6.8 After the decision — collapse to one camera

Once the winner is clear:

1. Set the default in `ml/config.py` so the live path needs no flags:
   ```python
   CAMERA_SOURCE    = "mjpeg"                           # or "webcam"
   ESP32_STREAM_URL = "http://192.168.4.1:81/stream"    # if mjpeg
   CAMERA_INDEX     = 0                                 # if webcam
   ```
2. Rename the winner's pair to the default names, and delete the loser's:
   ```bash
   mv references_webcam references && mv embedding_db_webcam.pkl embedding_db.pkl
   rm -rf references_esp32 embedding_db_esp32.pkl
   ```
3. **Keep the datasets.** `datasets/` is the only ground truth you have. Every future
   threshold change, model swap or prompt edit can be re-scored against it offline, for
   free, in seconds — and that is worth far more than the disk it occupies.
4. Re-run the end-to-end demo on the winner (§6.9).

---

### 6.9 End-to-end smoke test on the chosen camera

```bash
py -3 verify_demo.py
```

*(On the Pi: `python3 verify_demo.py`.)*

Controls: **S** = scan next SKU, **W** = weight change (auto-settles), **R** = reset,
**Q** = quit. Walk these cases in front of the mounted camera:

| Do this | Expect |
|---|---|
| Scan A, carry **A** across into the cart box, press **W** | **MATCH** |
| Scan A, carry a **different same-weight item** | **SUSPECT** (colour off) or **MISMATCH** (shape off) |
| Cover the item with your hand mid-transit | **RETRY** (broken custody) |
| Scan again mid-transit | old txn **RETRY**, new one starts |
| Rename `embedding_db.pkl`, scan anything | **UNAVAILABLE** (never a silent accept) |

**Then measure on the Pi.** The per-verdict latency printed is real *on this Pi* now (the
laptop figure was a target). If it's too slow or RAM is tight, tune in `ml/config.py`:
lower `VERIFY_BURST_FRAMES` (fewer crops → less RAM + faster), or adjust
`VERIFY_PASS_FRACTION`.

> **Known hole, must be fixed before this goes live in a real lane.**
> `ml/frame_source.py` keeps **newest-frame-only**, so frames are silently dropped when
> the consumer lags, and `ml/item_follower.py` dedupes repeated frames but never *detects
> gaps*. That contradicts the requirement that the item be tracked scan-to-basket without
> a frame skip. It does **not** affect the bake-off — §6 replays saved crops offline,
> where frame timing is irrelevant — but a dropped frame during a real transaction is a
> custody gap the system cannot currently see. Fix it before trusting a live verdict.

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
  you already installed), and **any DB you build with the default config is already
  stamped for it** — nothing to rebuild. Keep `ml/mobilenet_v2.onnx`; you may **delete
  `ml/mobilenet_v2_quant.tflite`** and drop `ai-edge-litert` from `requirements.txt`.
  For safety pin it explicitly:
  ```python
  EMBEDDING_BACKEND = "onnx"     # in ml/config.py — fail loudly if ONNX won't load
  ```
- **Only switch to TFLite** if ONNX won't load on your Pi *and* you measure TFLite fast
  enough there. If you do:
  1. keep `ml/mobilenet_v2_quant.tflite` and `ai-edge-litert`,
  2. set `EMBEDDING_BACKEND = "tflite"`,
  3. **rebuild the DB** — `py -3 build_db.py` — so it's re-stamped
     `tflite-mbv2quant-1280`. The matcher **refuses a mismatched-backend DB** (the two
     models produce numerically incompatible vectors), so skipping this makes the demo
     error out on load. That guard is intentional.

> The DB stamp is the safety interlock: it guarantees you never score live crops from
> one model against references embedded by the other.

> **Do this decision AFTER §6, not during it.** Switching the embedding backend
> mid-bake-off invalidates every number you've collected, because tests 1 and 3 would
> then be scored by two different models. Settle on one backend, rebuild **both**
> camera databases with it (`--references references_esp32 --out embedding_db_esp32.pkl`
> and the webcam pair), and only then run the comparison. From §6.8 onward there is one
> camera and one plain `embedding_db.pkl`, which is what §8 below assumes.

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

> This is the **post-bake-off** shape: one camera, named once in `CAMERA_SOURCE`, and
> one plain `embedding_db.pkl` — the winner's DB, renamed in §6.8. The `--source` /
> `--db` flags exist only for §6, where two cameras are live at once; production code
> reads config, not flags.

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

**General**

| Symptom | Likely cause / fix |
|---|---|
| Demo prints "No reference database" → all `UNAVAILABLE` | The `.pkl` is missing, or the SKU isn't in it. Run `build_db.py`; confirm the backend stamp. |
| Load error mentioning backend mismatch | DB stamped for a different model than `EMBEDDING_BACKEND`. Rebuild the DB (§7). |
| Never reaches `MATCH`; best case is always `SUSPECT` | Colour is disabled. At startup you'll see `[verifier] Colour references are format …` — the DB's colour stamp is stale. Rebuild with `build_db.py` (§6.3 A2). |
| "Waiting for camera stream…" forever | ESP32 URL/mode wrong, or the Pi isn't on the ESP32's network. Check the `curl` in §5a. |
| Webcam opens but every frame is black | Wrong `--index`, or another process holds the device. Try `--index 1`; close other camera apps. |
| Genuine matches score low | **Domain mismatch** — references weren't shot on *this* camera. Re-capture with the right `--source` (§6.3/§6.4). |
| Every transit ends `RETRY` (lost/ambiguous) | Regions don't match the mounted view, or lighting makes the follower drop the item. Adjust `SCANNER_REGION`/`CART_ENTRY_REGION` (§5c); check `VIS_*` floors. |
| Verdict too slow / RAM tight | Using TFLite where ONNX would do (§7), or `VERIFY_BURST_FRAMES` too high. Prefer ONNX; lower the burst. |

**Bake-off specific (§6)**

| Symptom | Likely cause / fix |
|---|---|
| A test reports `SKIPPED — no dataset` | You didn't pass that camera's `--<cam>-dataset`, or the directory doesn't exist under `datasets/`. |
| A test reports `SKIPPED — no API key` | `OPENROUTER_API_KEY` isn't set in *this* shell. Set it and re-run, or point `--base-url` at a local Ollama. |
| A test reports `SKIPPED — reference DB unusable` | The `--<cam>-db` path is wrong, or the DB was built with a different embedding backend. Rebuild it. This is reported as a **skip**, never as a run of all-failures, so a setup mistake can't masquerade as a bad camera. |
| One camera looks catastrophically worse than the other | **Check you passed the matching `--<cam>-db`.** Scoring one camera's crops against the other's references measures the domain gap, not the camera — it's the single easiest way to get a confidently wrong answer here. |
| `FAR or FRR cannot be computed` / `n/a` in the table | That dataset has only one label. You need both **G** and **X** transactions. |
| Both backends fail on the *same* cases | Not a model problem. Re-shoot references (`REFERENCE_SOP.md` §2) — usually lighting or too few poses. |
| AI test: every case comes back `RETRY` | Every AI failure path is fail-closed by design. Run `compare_backends.py --backends ai --verbose` — it prints the first real error (bad key, wrong model id, unreachable endpoint). |
| Numbers swing wildly between runs of the same dataset | You have too few cases. Re-scoring is deterministic for the local backend, so any swing is AI sampling or a tiny dataset. Capture more. |
