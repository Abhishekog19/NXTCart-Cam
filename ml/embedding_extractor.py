# ---------------------------------------------------------------
# ml/embedding_extractor.py
#
# WHAT IT DOES
# ─────────────
# 1. Downloads a pre-trained, quantized MobileNetV2 TFLite model
#    the first time it runs (saved locally so subsequent runs are
#    instant).
#
# 2. Loads the model with TFLite's Interpreter — this is a very
#    lightweight runtime; it does NOT train anything.
#
# 3. Exposes one public function:
#      extract_embedding(image) → numpy array of shape (1280,)
#
#    An "embedding" is just a list of 1280 numbers that the neural
#    network uses to represent what a photo looks like.  Similar
#    products produce similar embeddings, which is what lets us
#    compare photos without any custom training.
#
# WHY MOBILENETV2 TFLITE?
# ─────────────────────────
# – Very fast on CPU (no GPU required).
# – The quantized variant is ~3.4 MB, trivial to ship.
# – We strip the final classification layer and use the 1280-D
#   "global average pooling" layer as our feature vector.
# ---------------------------------------------------------------

import os
import urllib.request

import cv2
import numpy as np

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    # Fall back to the TFLite part bundled inside full TensorFlow.
    import tensorflow.lite as tflite

from ml.config import IMAGE_SIZE, MODEL_PATH

# ── Model URL ────────────────────────────────────────────────────
# This is Google's official quantized MobileNetV2 for TFLite.
# The model ends at the global-average-pooling layer (no softmax
# head), so its output IS the embedding we need.
_MODEL_URL = (
    "https://storage.googleapis.com/download.tensorflow.org/"
    "models/tflite_11_05_08/mobilenet_v2_1.0_224_quant.tflite"
)

# Module-level cache so we only load the model once per process.
_interpreter = None


def _download_model_if_needed() -> None:
    """Download the TFLite model file if it isn't already on disk."""
    if os.path.exists(MODEL_PATH):
        return  # already downloaded

    print(f"[embedding_extractor] Downloading MobileNetV2 TFLite model to {MODEL_PATH} …")
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    urllib.request.urlretrieve(_MODEL_URL, MODEL_PATH)
    print("[embedding_extractor] Download complete.")


def _get_interpreter() -> tflite.Interpreter:
    """
    Load (or return the cached) TFLite interpreter.

    TFLite's Interpreter is the engine that runs the model.
    We allocate tensors once and reuse the interpreter for every
    subsequent call — this avoids re-loading the model from disk
    every time we process a frame.
    """
    global _interpreter

    if _interpreter is not None:
        return _interpreter  # already loaded, return immediately

    _download_model_if_needed()

    _interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    _interpreter.allocate_tensors()  # pre-allocate memory for inputs/outputs
    print("[embedding_extractor] Model loaded and ready.")
    return _interpreter


def _preprocess(image: np.ndarray) -> np.ndarray:
    """
    Resize and normalise an image so it matches what MobileNetV2
    was trained on.

    Steps:
      1. Resize to IMAGE_SIZE × IMAGE_SIZE (224×224).
      2. Convert BGR (OpenCV default) → RGB.
      3. Cast to uint8 — the quantized model expects integer values 0-255.
      4. Add a batch dimension: shape (224, 224, 3) → (1, 224, 224, 3).

    NOTE: Full-precision MobileNetV2 uses (pixel/127.5 - 1) normalisation.
    The *quantized* variant keeps uint8 inputs; the model itself handles
    the scale internally.
    """
    # Resize to model's expected spatial dimensions.
    img = cv2.resize(image, (IMAGE_SIZE, IMAGE_SIZE))
    # OpenCV reads in BGR; MobileNetV2 was trained on RGB.
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    # Quantized model wants uint8.
    img = img.astype(np.uint8)
    # Models expect a batch of images, even when we only have one.
    img = np.expand_dims(img, axis=0)  # shape: (1, 224, 224, 3)
    return img


def extract_embedding(image: "str | np.ndarray") -> np.ndarray:
    """
    Given a product image, return its embedding vector.

    Parameters
    ----------
    image : str or numpy.ndarray
        Either a file path (str) or an already-loaded BGR image
        (as returned by cv2.imread or a webcam frame).

    Returns
    -------
    numpy.ndarray, shape (1280,), dtype float32
        L2-normalised embedding.  All values lie on the unit sphere,
        so cosine similarity reduces to a simple dot product.

    Raises
    ------
    FileNotFoundError  – if a path is given but the file is missing.
    ValueError         – if the image cannot be loaded.
    """
    # ── Load image if a file path was given ──────────────────────
    if isinstance(image, str):
        if not os.path.exists(image):
            raise FileNotFoundError(f"Image file not found: {image}")
        image = cv2.imread(image)
        if image is None:
            raise ValueError(f"cv2.imread could not read: {image}")

    # ── Pre-process ───────────────────────────────────────────────
    input_data = _preprocess(image)

    # ── Run the model ─────────────────────────────────────────────
    interp = _get_interpreter()

    # Where to feed data in, and where to read data out.
    input_details = interp.get_input_details()
    output_details = interp.get_output_details()

    interp.set_tensor(input_details[0]["index"], input_data)
    interp.invoke()  # actually run the neural network

    # Output tensor has shape (1, 1280) — squeeze the batch dim.
    raw = interp.get_tensor(output_details[0]["index"])  # shape (1, 1280)
    embedding = raw[0].astype(np.float32)                # shape (1280,)

    # ── L2-normalise ─────────────────────────────────────────────
    # Dividing by the vector's length puts it on the unit sphere.
    # This makes cosine similarity equivalent to a plain dot product
    # and removes brightness/contrast differences between photos.
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding
