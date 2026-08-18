# NXTCart-Cam — Product Recognition System

Camera module backend for the NXTcart smart shopping cart project.

Identifies products from a live webcam by comparing image embeddings
(MobileNetV2 TFLite, no training required) against a reference database
you build yourself.

---

## Project Structure

```
NXTCart-Cam/
├── references/                ← you populate this; one sub-folder per product
│   └── <product_name>/
│       ├── 001.jpg
│       └── ...
├── ml/
│   ├── __init__.py            ← makes ml/ a Python package
│   ├── config.py              ← ALL tunable thresholds in one place
│   ├── embedding_extractor.py ← MobileNetV2 TFLite feature extractor
│   ├── matcher.py             ← cosine similarity + confidence logic
│   └── multi_frame_vote.py   ← burst-capture majority voting
├── capture_references.py      ← step 1: build your reference photo set
├── build_db.py                ← step 2: compute & save embeddings
├── demo.py                    ← step 3: run on demo day
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
