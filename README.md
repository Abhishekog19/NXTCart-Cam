# NXTCart-Cam — Product Verification System

**Integrated dual-webcam cart runtime (2026-10-09):** Start with
[`SYSTEM_SETUP.md`](SYSTEM_SETUP.md). This folder supplies the **PC-only** camera
verification service in `pc/`; the Raspberry Pi, Arduino, scale, catalogue,
display and cart authority live in the separate `../Cart-RestCode/` folder.
Scans appear immediately. Weight and camera update independently. Shopping
continues through red items; checkout requires every unit to pass both gates.
Choose `backend:=local` or `backend:=ai` on the PC without changing the Pi.

The standalone demos and older integration/deployment notes below are retained
for reference. They do **not** define the new runtime or its billing policy.
The current integration tests are `python -m unittest discover -s tests -v`.

Camera module for the NXTcart smart shopping cart.

Given that the barcode says "SKU X", it answers one question — **is the item that
just entered the cart actually X?** — by comparing image embeddings
(MobileNetV2, no training required) plus a colour fingerprint against a reference
database you build yourself. It exists to catch the one attack weight cannot see:
**scan a cheap item, insert an expensive one of the same weight.**

### Start here

| I want to… | Read |
|---|---|
| **Set up, mount the camera, photograph products, and test today** | [`SETUP_AND_TEST.md`](SETUP_AND_TEST.md) |
| Compare local ML with DeepSeek vision AI, references, frame selection and accuracy | [`ML_VS_AI_TEST_GUIDE.md`](ML_VS_AI_TEST_GUIDE.md) |
| Join this to the ROS 2 cart (`smart_cart_ws`) | [`CART_INTEGRATION.md`](CART_INTEGRATION.md) |
| Deploy to the Pi / choose a camera by measurement | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Shoot reference photos properly | [`REFERENCE_SOP.md`](REFERENCE_SOP.md) |
| Understand why it is built this way | [`ARCHITECTURE.md`](ARCHITECTURE.md) |

```bash
py -3 test_verify.py        # camera logic      (no camera/model needed)
py -3 test_cart_logic.py    # cart billing + anti-swap
py -3 cart_sim.py --index 1 # test on real products with a webcam
```

> On Windows use `py -3`, not `python`.

---

## Project Structure

```
NXTCart-Cam/
├── references/                ← you populate this; one sub-folder per product
│   └── <product_name>/
│       ├── 001.jpg
│       └── ...
├── ml/
│   ├── config.py              ← ALL tunable thresholds in one place
│   ├── frame_source.py        ← webcam / ESP32-CAM, seq+ts stamped frames
│   ├── detector.py            ← motion blob detector
│   ├── item_follower.py       ← locks and follows ONE item scanner→cart
│   ├── visibility.py          ← "is this view judgeable?"
│   ├── product_crop.py        ← one crop definition for refs AND live
│   ├── verifier.py            ← MATCH/SUSPECT/MISMATCH/RETRY/UNAVAILABLE
│   ├── custody.py             ← one scan, one transaction, two proofs
│   ├── cart.py                ← running cart + bill (standalone)
│   ├── lane.py                ← the whole module as ONE object
│   ├── events.py              ← barcode + weight seams (mock and real)
│   ├── embedding_extractor.py ← MobileNetV2 feature extractor
│   └── matcher.py             ← cosine similarity + backend-stamp guard
├── capture_references.py      ← step 1: shoot your reference photos
├── build_db.py                ← step 2: compute & save embeddings + colour
├── cart_sim.py                ← step 3: test on real products (webcam)
├── verify_demo.py             ← minimal single-verdict demo
├── test_verify.py             ← camera logic suite
├── test_cart_logic.py         ← cart billing / anti-swap suite
└── requirements.txt
```

---

## Setup

```bash
pip install -r requirements.txt
```

> **Note:** `tflite-runtime` is a lightweight runtime (~7 MB).
> If you prefer, you can instead install `tensorflow` and skip
> `tflite-runtime` — the code falls back automatically.

---

## Workflow

### Step 1 — Capture reference photos

```bash
python capture_references.py
```

For each product:
1. Type the product name and press **Enter**
2. A webcam preview opens
3. Press **SPACE** to save a photo, aim for **5–8 photos per product**
   (different angles, slight distance changes)
4. Press **Q** when done → type the next product name

Photos save to `references/<product_name>/`.

---

### Step 2 — Build the embedding database

```bash
python build_db.py
```

Processes every image in `references/` and saves `embedding_db.pkl`.
Re-run this every time you add or remove reference photos.

---

### Step 3 — Run the live demo

```bash
python demo.py
```

| Key | Action |
|-----|--------|
| `SPACE` | Trigger a 5-frame scan and show the confirmed result |
| `Q` | Quit |

The window shows:
- Live camera feed with a continuous single-frame prediction
- After a scan: product name, score %, margin %, and a **CONFIDENT / UNCERTAIN** verdict

---

## Tuning Thresholds

All thresholds are in [`ml/config.py`](ml/config.py):

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `SCORE_THRESHOLD` | `0.78` | Minimum cosine similarity to call a match confident |
| `MARGIN_THRESHOLD` | `0.06` | Minimum gap between #1 and #2 products |
| `NUM_FRAMES` | `5` | Frames captured per scan |
| `AGREE_THRESHOLD` | `3` | Frames that must agree for a confirmed answer |
| `CAMERA_INDEX` | `0` | Webcam index (change if wrong camera opens) |

If you get too many "uncertain" results → lower `SCORE_THRESHOLD`.
If you get wrong confident results → raise `SCORE_THRESHOLD` or lower `MARGIN_THRESHOLD`.

---

## How It Works (plain language)

1. **MobileNetV2** is a neural network trained on millions of images.
   We don't train it further — we use it as a "visual fingerprinter".
   For any photo it produces a list of 1280 numbers (an "embedding")
   that summarises what the image looks like.

2. **build_db.py** runs your reference photos through this fingerprinter
   and saves the results.

3. When you hold up a product, **demo.py** fingerprints the live frame
   and compares it against every reference embedding using cosine
   similarity (how "close" two fingerprints are in direction).

4. The product whose *best* reference is most similar wins. If the
   winning score is above the threshold AND it's clearly ahead of
   the second-best product (margin), we call it **confident**.

5. **Multi-frame voting** captures 5 frames in ~0.7 seconds and only
   confirms a result if at least 3 frames independently agree —
   catching blur, reflection, or partial occlusion.
