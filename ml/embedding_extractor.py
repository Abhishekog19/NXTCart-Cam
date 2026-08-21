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
# HOW THE EMBEDDING IS EXTRACTED
# ───────────────────────────────
# The downloadable model is the full MobileNetV2 classifier (output
# shape [1, 1001] — 1001 ImageNet class probabilities).  We do NOT
# use that final output.  Instead, we read the INTERNAL tensor at
# the "global average pooling" layer (tensor index discovered at
# load-time by scanning for the tensor named "…/Logits/AvgPool").
# That tensor has shape (1, 1, 1, 1280) — we flatten it to (1280,).
# This is the standard "strip the classification head" technique.
#
# WHY MOBILENETV2 TFLITE?
# ─────────────────────────
# – Very fast on CPU (no GPU required).
# – The quantized variant is ~3.4 MB, trivial to ship.
# – The 1280-D pooling layer is an excellent general-purpose
#   feature vector for similarity matching.
# ---------------------------------------------------------------

import os

import cv2
import numpy as np

# ── Windows DLL search path fix ──────────────────────────────────
# On Python 3.14 for Windows, the VC++ runtime DLLs (vcruntime140.dll,
# msvcp140.dll) live inside Python's own install directory but are not
# automatically on the DLL search path.  ai-edge-litert's native
# extension needs them, so we add that directory explicitly.
import sys
if sys.platform == "win32":
    import pathlib
    _py_dir = pathlib.Path(sys.executable).parent
    try:
        os.add_dll_directory(str(_py_dir))
    except (AttributeError, OSError):
        pass  # older Python or path already searched

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    try:
        # ai-edge-litert is Google's new distribution of the TFLite runtime.
        # It supports Python 3.13+ and is the correct package for Python 3.14.
        import ai_edge_litert.interpreter as tflite
    except ImportError:
        # Last resort: the TFLite interpreter bundled inside full TensorFlow.
        import tensorflow.lite as tflite

from ml.config import IMAGE_SIZE, MODEL_PATH

# ── Model download URL ───────────────────────────────────────────
# Why this specific URL?
#
# The "official" download.tensorflow.org links return HTTP 403 on
# many networks (Google has tightened access to the public model
# bucket).  GitHub raw content still works reliably.
#
# This is the same MobileNetV2 1.0 224 quantized model — full
# classifier variant.  We extract the 1280-D embedding from its
# internal global-average-pooling tensor (see _find_embedding_tensor).
_MODEL_URL = (
    "https://raw.githubusercontent.com/google-coral/test_data/"
    "master/mobilenet_v2_1.0_224_quant.tflite"
)

# Minimum plausible file size for the real model (~3.4 MB).
# An HTML error page would typically be < 50 KB.
_MIN_MODEL_BYTES = 1_000_000

# Module-level caches — load only once per process.
_interpreter = None
_embedding_tensor_index = None   # index of the 1280-D AvgPool tensor
_embedding_quant = None          # (scale, zero_point) for dequantization


# ─────────────────────────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────────────────────────

def _download_model_if_needed() -> None:
    """
    Download the TFLite model if it isn't already on disk.

    Validates that the downloaded content is:
      • an HTTP 200 response
      • a binary file (not an HTML/XML error page)
      • large enough to be a real model (> 1 MB)

    Raises RuntimeError with a clear message on failure.
    The download is attempted ONCE.  If it fails, the error
    propagates immediately — individual image calls never retry.
    """
    if os.path.exists(MODEL_PATH):
        size = os.path.getsize(MODEL_PATH)
        if size >= _MIN_MODEL_BYTES:
            return  # already on disk and looks valid
        # File exists but is too small — likely a corrupt download.
        print(f"[embedding_extractor] Existing model file is only {size} bytes — re-downloading.")
        os.remove(MODEL_PATH)

    import requests

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    print(f"[embedding_extractor] Downloading MobileNetV2 model from:")
    print(f"  {_MODEL_URL}")

    try:
        response = requests.get(
            _MODEL_URL,
            headers={"User-Agent": "NXTCart-Cam/1.0"},
            timeout=120,
        )
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(
            f"Could not download the MobileNetV2 TFLite model.\n"
            f"  URL: {_MODEL_URL}\n"
            f"  Error: {type(e).__name__}: {e}\n\n"
            f"To fix this manually, download the file from a browser and\n"
            f"save it to: {MODEL_PATH}"
        ) from e

    content = response.content

    # ── Validate the response is actually a model, not an error page ──
    content_type = response.headers.get("Content-Type", "")
    if "html" in content_type.lower() or "xml" in content_type.lower():
        raise RuntimeError(
            f"Server returned an HTML/XML page instead of a model file.\n"
            f"  Content-Type: {content_type}\n"
            f"  This usually means the URL is incorrect or access is blocked."
        )

    if len(content) < _MIN_MODEL_BYTES:
        raise RuntimeError(
            f"Downloaded file is only {len(content)} bytes — too small to be\n"
            f"a valid TFLite model (expected ~3.4 MB).  The server may have\n"
            f"returned an error page."
        )

    with open(MODEL_PATH, "wb") as f:
        f.write(content)

    print(f"[embedding_extractor] Download complete: {len(content):,} bytes saved to {MODEL_PATH}")


# ─────────────────────────────────────────────────────────────────
# INTERPRETER + EMBEDDING TENSOR DISCOVERY
# ─────────────────────────────────────────────────────────────────

def _find_embedding_tensor(interp: tflite.Interpreter) -> tuple:
    """
    Scan all tensors in the loaded model and find the 1280-D global
    average pooling layer — this is our embedding output.

    In MobileNetV2 the tensor is named "MobilenetV2/Logits/AvgPool"
    and has shape (1, 1, 1, 1280).  We search by both name and shape
    for robustness.

    Returns
    -------
    (tensor_index, scale, zero_point)
    """
    details = interp.get_tensor_details()

    # Strategy 1: find by name (most reliable).
    for d in details:
        if "AvgPool" in d["name"] and 1280 in d["shape"]:
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    # Strategy 2: find by shape (1, 1, 1, 1280) — any name.
    for d in details:
        shape = tuple(d["shape"])
        if shape == (1, 1, 1, 1280):
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    # Strategy 3: find any tensor with exactly 1280 as last dim.
    for d in details:
        shape = tuple(d["shape"])
        if len(shape) >= 2 and shape[-1] == 1280 and d["dtype"] == np.uint8:
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    raise RuntimeError(
        "Could not find the 1280-D embedding tensor in the model.\n"
        "The model file may be corrupted or a different architecture."
    )


def _get_interpreter() -> tflite.Interpreter:
    """
    Load (or return the cached) TFLite interpreter and locate the
    embedding tensor.

    Uses BUILTIN_WITHOUT_DEFAULT_DELEGATES to disable the XNNPACK
    delegate, which causes a hard crash on some Windows builds of
    ai-edge-litert.  The model runs fine on pure CPU kernels.
    """
    global _interpreter, _embedding_tensor_index, _embedding_quant

    if _interpreter is not None:
        return _interpreter

    _download_model_if_needed()

    _interpreter = tflite.Interpreter(
        model_path=MODEL_PATH,
        experimental_op_resolver_type=tflite.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
    )
    _interpreter.allocate_tensors()

    # Discover the 1280-D embedding tensor inside the model.
    idx, scale, zp = _find_embedding_tensor(_interpreter)
    _embedding_tensor_index = idx
    _embedding_quant = (scale, zp)

    # Log what we found so the user can verify.
    out_official = _interpreter.get_output_details()[0]
    print(f"[embedding_extractor] Model loaded successfully.")
    print(f"  Official output: shape={tuple(out_official['shape'])} (classification — ignored)")
    print(f"  Embedding tensor: index={idx}, scale={scale}, zero_point={zp}")
    print(f"  Embedding dimension: 1280")

    return _interpreter


# ─────────────────────────────────────────────────────────────────
# PREPROCESSING
# ─────────────────────────────────────────────────────────────────

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
    img = cv2.resize(image, (IMAGE_SIZE, IMAGE_SIZE))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.uint8)
    img = np.expand_dims(img, axis=0)  # shape: (1, 224, 224, 3)
    return img


# ─────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────

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
            raise ValueError(f"cv2.imread could not read the file")

    # ── Pre-process ───────────────────────────────────────────────
    input_data = _preprocess(image)

    # ── Run the model ─────────────────────────────────────────────
    interp = _get_interpreter()

    input_details = interp.get_input_details()
    interp.set_tensor(input_details[0]["index"], input_data)
    interp.invoke()

    # ── Read the embedding from the internal AvgPool tensor ──────
    # NOT the official output (which is the 1001-class softmax).
    raw = interp.get_tensor(_embedding_tensor_index)  # shape (1,1,1,1280) uint8

    # Dequantize: float_value = (uint8_value - zero_point) * scale
    scale, zero_point = _embedding_quant
    embedding = (raw.flatten().astype(np.float32) - zero_point) * scale

    # ── L2-normalise ─────────────────────────────────────────────
    # Dividing by the vector's length puts it on the unit sphere.
    # This makes cosine similarity equivalent to a plain dot product
    # and removes brightness/contrast differences between photos.
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding
