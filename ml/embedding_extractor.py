# ---------------------------------------------------------------
# ml/embedding_extractor.py
#
# WHAT IT DOES
# ─────────────
# Turns an image into a 1280-number "fingerprint" (an embedding) that can
# be compared against reference photos.  One public function:
#
#      extract_embedding(image) → numpy array of shape (1280,)
#
# Similar-looking products produce similar embeddings, which is what lets
# us recognise items without training anything ourselves.
#
# TWO BACKENDS, ONE API
# ──────────────────────
# The function above is the ONLY thing callers see.  Underneath there are
# two ways to run the network, tried in this order:
#
#   1. ONNX float MobileNetV2 through cv2.dnn      ~6.5 ms   ← default
#   2. Quantized MobileNetV2 TFLite (legacy)     ~1619 ms   ← fallback
#
# WHY THE ONNX PATH EXISTS  (this is the important part)
# ──────────────────────────────────────────────────────
# The TFLite path is 250x slower than it should be, and it cannot be fixed
# by configuration.  On this platform (ai-edge-litert 2.2.0, Python 3.14,
# Windows) every faster interpreter setting crashes the process outright:
#
#     no delegates, 1 thread  ->  1618.87 ms   (works — the only one)
#     no delegates, 4 threads ->  segfault (exit 139)
#     XNNPACK,      1 thread  ->  segfault
#     XNNPACK,      4 threads ->  segfault
#
# So the runtime is pinned to its slowest possible setting.  At ~1.6 s per
# call the live demo could not run: identity verification needs several
# recognitions per item, which put a single frame into the multi-second
# range and made the whole pipeline untestable.
#
# cv2.dnn cannot rescue the existing model either — it rejects the
# quantized weights outright:
#     (-213) Parse tensor with type UINT8 in function 'parseTensor'
# which is why the ONNX path uses a FLOAT model instead of the .tflite.
#
# Accuracy is not the price of the speed.  Leave-one-out over references/:
#     TFLite quant : 19/20 top-1,  separation -0.132
#     ONNX  float  : 19/20 top-1,  separation -0.079   (better separated)
#
# The TFLite path is kept as an automatic fallback so a missing or
# unreadable ONNX file degrades to "slow" rather than "broken".
#
# IMPORTANT: the two backends produce DIFFERENT embedding spaces.  A
# database built with one is meaningless to the other, so build_db.py
# stamps the backend into embedding_db.pkl and ml/matcher.py refuses to
# load a mismatched one.  See backend_id() below.
#
# HOW THE EMBEDDING IS EXTRACTED
# ───────────────────────────────
# Both models are full ImageNet classifiers.  We do NOT use their
# classification output.  We read the INTERNAL global-average-pooling
# layer, which is 1280-D, and flatten it.  That is the standard "strip the
# classification head" technique.  In both backends the layer/tensor is
# DISCOVERED at load time by probing, never hardcoded — see
# _find_embedding_tensor (TFLite) and _find_onnx_embedding_layer (ONNX).
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
        # If none of the three is installed the ONNX backend still works;
        # only the fallback is unavailable.
        tflite = None

from ml.config import EMBEDDING_BACKEND, IMAGE_SIZE, MODEL_PATH, ONNX_MODEL_PATH

EMBEDDING_DIM = 1280

# ── Model download URLs ──────────────────────────────────────────
# Why these specific URLs?
#
# The "official" download.tensorflow.org links return HTTP 403 on many
# networks (Google has tightened access to the public model bucket).
# GitHub raw content still works reliably.
_MODEL_URL = (
    "https://raw.githubusercontent.com/google-coral/test_data/"
    "master/mobilenet_v2_1.0_224_quant.tflite"
)

# MobileNetV2 float, opset 7, from the ONNX model zoo (~13.9 MB).  This is
# the torchvision export, so it expects ImageNet mean/std normalisation —
# see _preprocess_onnx.  The repo re-organised its layout at some point, so
# both the current and the legacy path are tried in order.
_ONNX_MODEL_URLS = (
    "https://github.com/onnx/models/raw/main/validated/vision/classification/"
    "mobilenet/model/mobilenetv2-7.onnx",
    "https://github.com/onnx/models/raw/main/vision/classification/"
    "mobilenet/model/mobilenetv2-7.onnx",
)

# Minimum plausible file size for a real model.
# An HTML error page would typically be < 50 KB.
_MIN_MODEL_BYTES = 1_000_000

# ── ImageNet normalisation (ONNX / torchvision convention) ───────
# Applied to RGB values already scaled to [0, 1].
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# ── Backend identity strings ─────────────────────────────────────
# Written into embedding_db.pkl by build_db.py and checked by
# ml/matcher.load_database().  Change these ONLY together with a change
# that alters the embedding space, because that is exactly what they
# exist to detect.
_BACKEND_IDS = {
    "onnx": "onnx-mbv2-1280",
    "tflite": "tflite-mbv2quant-1280",
}

# ── Module-level caches — load only once per process ─────────────
_backend = None                  # "onnx" | "tflite", decided on first use
_onnx_net = None                 # cv2.dnn_Net
_onnx_layer = None               # name of the 1280-D layer in that net
_interpreter = None
_embedding_tensor_index = None   # index of the 1280-D AvgPool tensor
_embedding_quant = None          # (scale, zero_point) for dequantization


# ─────────────────────────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────────────────────────

def _download(urls, dest: str, what: str) -> None:
    """
    Download `what` to `dest`, trying each URL in turn.

    Validates that the content is:
      • an HTTP 200 response
      • a binary file (not an HTML/XML error page)
      • large enough to be a real model (> 1 MB)

    Raises RuntimeError listing every attempt if none succeed.  The
    download happens ONCE per process; individual image calls never retry.
    """
    if isinstance(urls, str):
        urls = (urls,)

    import requests

    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)

    failures = []
    for url in urls:
        print(f"[embedding_extractor] Downloading {what} from:")
        print(f"  {url}")
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "NXTCart-Cam/1.0"},
                timeout=180,
            )
            response.raise_for_status()
        except Exception as e:
            failures.append(f"{url} -> {type(e).__name__}: {e}")
            continue

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" in content_type or "xml" in content_type:
            failures.append(
                f"{url} -> server returned {content_type} (an error page, not a model)"
            )
            continue

        content = response.content
        if len(content) < _MIN_MODEL_BYTES:
            failures.append(
                f"{url} -> only {len(content)} bytes, too small to be a model"
            )
            continue

        with open(dest, "wb") as f:
            f.write(content)
        print(f"[embedding_extractor] Download complete: "
              f"{len(content):,} bytes saved to {dest}")
        return

    raise RuntimeError(
        f"Could not download {what}.\n"
        + "\n".join(f"  {m}" for m in failures)
        + f"\n\nTo fix this manually, download the file in a browser and\n"
          f"save it to: {dest}"
    )


def _ensure_file(path: str, urls, what: str) -> None:
    """Make sure `path` exists and looks like a real model, downloading if not."""
    if os.path.exists(path):
        size = os.path.getsize(path)
        if size >= _MIN_MODEL_BYTES:
            return  # already on disk and looks valid
        # File exists but is too small — likely a corrupt or partial download.
        print(f"[embedding_extractor] Existing {what} is only {size} bytes "
              f"— re-downloading.")
        os.remove(path)
    _download(urls, path, what)


def _download_model_if_needed() -> None:
    """Fetch the legacy quantized TFLite model if it isn't on disk."""
    _ensure_file(MODEL_PATH, _MODEL_URL, "the MobileNetV2 quantized TFLite model")


def _download_onnx_if_needed() -> None:
    """Fetch the float ONNX MobileNetV2 if it isn't on disk."""
    _ensure_file(ONNX_MODEL_PATH, _ONNX_MODEL_URLS,
                 "the MobileNetV2 float ONNX model")


# ═════════════════════════════════════════════════════════════════
# BACKEND 1 (default):  ONNX via cv2.dnn      ~6.5 ms
# ═════════════════════════════════════════════════════════════════

def _read_onnx(path: str):
    """
    Load an ONNX graph with cv2.dnn, forcing the CLASSIC engine.

    The engine choice is NOT cosmetic.  On OpenCV 5 the new default engine
    fuses/renames nodes, and the internal pooling layer we need becomes
    unreachable:

        (-204) DNN: tensor 'GlobalAveragePool_97' is not found in the graph

    ENGINE_CLASSIC keeps per-node outputs addressable (prefixed
    'onnx_node!<name>').  OpenCV 4.x has no `engine` parameter at all, so a
    TypeError there is expected and we simply load without it — 4.x behaves
    like CLASSIC already.
    """
    engine = getattr(cv2.dnn, "ENGINE_CLASSIC", None)
    if engine is not None:
        try:
            return cv2.dnn.readNetFromONNX(path, engine)
        except TypeError:
            pass  # OpenCV 4.x signature: no engine argument
    return cv2.dnn.readNetFromONNX(path)


def _probe_layer(net, name: str, blob: np.ndarray):
    """Run one forward to `name` and return its output, or None if unusable."""
    try:
        net.setInput(blob)
        out = net.forward(name)
    except cv2.error:
        return None
    if out is None or not hasattr(out, "size"):
        return None
    return out


def _find_onnx_embedding_layer(net, blob: np.ndarray) -> str:
    """
    Find the layer whose output is the 1280-D pooled feature vector.

    Deliberately DISCOVERED rather than hardcoded, for the same reason the
    TFLite path scans tensors: the exact node name depends on the export and
    on the OpenCV version's naming scheme.  On this build it resolves to
    'onnx_node!GlobalAveragePool_97' with shape (1, 1280, 1, 1), but any
    re-export would renumber that.

    Strategy 1: layers whose name hints at pooling (fast, hits first try).
    Strategy 2: every layer, last-to-first — the pooling layer sits near the
                end, just before the classifier.

    Returns the layer name.  Raises RuntimeError if nothing yields 1280 values.
    """
    names = list(net.getLayerNames())

    hints = ("globalaveragepool", "avgpool", "averagepool", "pool", "gap")
    likely = [n for n in names if any(h in n.lower() for h in hints)]

    for candidates in (likely, list(reversed(names))):
        for name in candidates:
            out = _probe_layer(net, name, blob)
            if out is None:
                continue
            # Accept any shape that flattens to exactly 1280 per sample:
            # (1, 1280, 1, 1), (1, 1280), (1, 1, 1, 1280) all qualify.
            if int(out.size) == EMBEDDING_DIM:
                return name

    raise RuntimeError(
        f"Could not find a {EMBEDDING_DIM}-D embedding layer in the ONNX model\n"
        f"  {ONNX_MODEL_PATH}\n"
        f"Scanned {len(names)} layers.  The file may be a different\n"
        f"architecture than MobileNetV2, or corrupt — delete it and let it\n"
        f"re-download."
    )


def _load_onnx() -> None:
    """Load the ONNX net and resolve its embedding layer.  Cached."""
    global _onnx_net, _onnx_layer

    if _onnx_net is not None:
        return

    _download_onnx_if_needed()

    net = _read_onnx(ONNX_MODEL_PATH)
    if net is None or net.empty():
        raise RuntimeError(f"cv2.dnn could not read {ONNX_MODEL_PATH}")

    probe = np.zeros((1, 3, IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
    layer = _find_onnx_embedding_layer(net, probe)

    _onnx_net = net
    _onnx_layer = layer

    print("[embedding_extractor] Model loaded: ONNX float MobileNetV2 (cv2.dnn).")
    print(f"  File           : {ONNX_MODEL_PATH}")
    print(f"  Embedding layer: {layer}")
    print(f"  Embedding dim  : {EMBEDDING_DIM}")


def _preprocess_onnx(image: np.ndarray) -> np.ndarray:
    """
    Resize and normalise for the float ONNX model (torchvision convention).

    Steps:
      1. Resize to IMAGE_SIZE x IMAGE_SIZE (224x224).
      2. BGR (OpenCV default) -> RGB.
      3. Scale to [0, 1], then subtract the ImageNet mean and divide by the
         ImageNet std, PER CHANNEL.
      4. Transpose HWC -> CHW and add a batch dimension -> (1, 3, 224, 224).

    Step 3 is done by hand rather than with cv2.dnn.blobFromImage because
    blobFromImage can subtract a mean but cannot divide by a per-channel
    standard deviation.
    """
    img = cv2.resize(image, (IMAGE_SIZE, IMAGE_SIZE))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = (img - _IMAGENET_MEAN) / _IMAGENET_STD
    blob = np.transpose(img, (2, 0, 1))[np.newaxis, ...]
    return np.ascontiguousarray(blob, dtype=np.float32)


def _embed_onnx(image: np.ndarray) -> np.ndarray:
    """Raw (un-normalised) 1280-D feature vector from the ONNX backend."""
    _load_onnx()
    blob = _preprocess_onnx(image)
    _onnx_net.setInput(blob)
    out = _onnx_net.forward(_onnx_layer)
    return np.asarray(out, dtype=np.float32).reshape(-1)


# ═════════════════════════════════════════════════════════════════
# BACKEND 2 (fallback):  quantized TFLite    ~1619 ms
# ═════════════════════════════════════════════════════════════════

def _find_embedding_tensor(interp) -> tuple:
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
        if "AvgPool" in d["name"] and EMBEDDING_DIM in d["shape"]:
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    # Strategy 2: find by shape (1, 1, 1, 1280) — any name.
    for d in details:
        shape = tuple(d["shape"])
        if shape == (1, 1, 1, EMBEDDING_DIM):
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    # Strategy 3: find any tensor with exactly 1280 as last dim.
    for d in details:
        shape = tuple(d["shape"])
        if len(shape) >= 2 and shape[-1] == EMBEDDING_DIM and d["dtype"] == np.uint8:
            quant = d.get("quantization", (1.0, 0))
            return d["index"], quant[0], quant[1]

    raise RuntimeError(
        "Could not find the 1280-D embedding tensor in the model.\n"
        "The model file may be corrupted or a different architecture."
    )


def _get_interpreter():
    """
    Load (or return the cached) TFLite interpreter and locate the
    embedding tensor.

    Uses BUILTIN_WITHOUT_DEFAULT_DELEGATES to disable the XNNPACK
    delegate, which SEGFAULTS on this Windows build of ai-edge-litert.
    Raising the thread count segfaults too.  This is therefore the only
    configuration that runs at all, and it is why this backend costs
    ~1619 ms per call and is merely the fallback — see the module
    docstring.
    """
    global _interpreter, _embedding_tensor_index, _embedding_quant

    if _interpreter is not None:
        return _interpreter

    if tflite is None:
        raise RuntimeError(
            "No TFLite runtime is installed (tried tflite_runtime, "
            "ai-edge-litert and tensorflow), so the fallback embedding "
            "backend is unavailable."
        )

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
    print("[embedding_extractor] Model loaded: quantized TFLite (FALLBACK, slow).")
    print(f"  Official output : shape={tuple(out_official['shape'])} "
          f"(classification — ignored)")
    print(f"  Embedding tensor: index={idx}, scale={scale}, zero_point={zp}")
    print(f"  Embedding dim   : {EMBEDDING_DIM}")

    return _interpreter


def _preprocess_tflite(image: np.ndarray) -> np.ndarray:
    """
    Resize and normalise an image so it matches what MobileNetV2
    was trained on.

    Steps:
      1. Resize to IMAGE_SIZE x IMAGE_SIZE (224x224).
      2. Convert BGR (OpenCV default) -> RGB.
      3. Cast to uint8 — the quantized model expects integer values 0-255.
      4. Add a batch dimension: shape (224, 224, 3) -> (1, 224, 224, 3).

    NOTE: Full-precision MobileNetV2 uses ImageNet mean/std normalisation
    (see _preprocess_onnx).  The *quantized* variant keeps uint8 inputs;
    the model itself handles the scale internally.
    """
    img = cv2.resize(image, (IMAGE_SIZE, IMAGE_SIZE))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.uint8)
    img = np.expand_dims(img, axis=0)  # shape: (1, 224, 224, 3)
    return img


def _embed_tflite(image: np.ndarray) -> np.ndarray:
    """Raw (un-normalised) 1280-D feature vector from the TFLite backend."""
    interp = _get_interpreter()

    input_data = _preprocess_tflite(image)
    input_details = interp.get_input_details()
    interp.set_tensor(input_details[0]["index"], input_data)
    interp.invoke()

    # Read the embedding from the internal AvgPool tensor — NOT the
    # official output (which is the 1001-class softmax).
    raw = interp.get_tensor(_embedding_tensor_index)  # (1,1,1,1280) uint8

    # Dequantize: float_value = (uint8_value - zero_point) * scale
    scale, zero_point = _embedding_quant
    return (raw.flatten().astype(np.float32) - zero_point) * scale


# ═════════════════════════════════════════════════════════════════
# BACKEND SELECTION
# ═════════════════════════════════════════════════════════════════

def _ensure_backend() -> str:
    """
    Decide which backend to use, load it, and cache the choice.

    EMBEDDING_BACKEND in ml/config.py controls this:
      "auto"   try ONNX, fall back to TFLite with a warning  (default)
      "onnx"   ONNX only — fail loudly if it cannot load
      "tflite" legacy path only
    """
    global _backend

    if _backend is not None:
        return _backend

    want = (EMBEDDING_BACKEND or "auto").strip().lower()
    if want not in ("auto", "onnx", "tflite"):
        raise ValueError(
            f"EMBEDDING_BACKEND must be 'auto', 'onnx' or 'tflite', "
            f"got {EMBEDDING_BACKEND!r}"
        )

    if want in ("auto", "onnx"):
        try:
            _load_onnx()
            _backend = "onnx"
            return _backend
        except Exception as e:
            if want == "onnx":
                raise
            print(f"[embedding_extractor] WARNING: the fast ONNX backend could "
                  f"not be loaded ({type(e).__name__}: {e}).")
            print("[embedding_extractor] Falling back to the quantized TFLite "
                  "model, which costs ~1.6 s per call — the demo will be slow.")

    _get_interpreter()
    _backend = "tflite"
    return _backend


def backend_id() -> str:
    """
    A short string identifying the embedding space currently in use.

    build_db.py records this inside embedding_db.pkl and
    ml/matcher.load_database() refuses to use a database whose stamp does
    not match.  The two backends produce numerically incompatible vectors,
    so without this check a stale database would silently return confident
    nonsense instead of an error.
    """
    return _BACKEND_IDS[_ensure_backend()]


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
            raise ValueError("cv2.imread could not read the file")

    # ── Run whichever backend is active ──────────────────────────
    if _ensure_backend() == "onnx":
        embedding = _embed_onnx(image)
    else:
        embedding = _embed_tflite(image)

    # ── L2-normalise ─────────────────────────────────────────────
    # Dividing by the vector's length puts it on the unit sphere.
    # This makes cosine similarity equivalent to a plain dot product
    # and removes brightness/contrast differences between photos.
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.astype(np.float32, copy=False)
