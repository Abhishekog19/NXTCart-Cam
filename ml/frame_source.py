# ---------------------------------------------------------------
# ml/frame_source.py  --  ONE FRAME, ONE IDENTITY
#
# WHY THIS FILE EXISTS
# ─────────────────────
# The verifier votes over multiple frames.  That is only safe if "multiple
# frames" really means multiple DISTINCT captures — if the same physical
# frame were read twice and scored twice, one lucky (or unlucky) image
# would get two votes and the multi-view smoothing would be a lie.
#
# So every frame that leaves this module carries an IDENTITY: a monotonic
# sequence number and a capture timestamp (FrameMeta).  Downstream code
# keys its per-frame work on `seq`, so re-reading the newest frame while
# the camera has not produced a new one yields the SAME seq and therefore
# cannot become a second vote.
#
# WHY A SEAM AT ALL
# ──────────────────
# Tonight the camera is a laptop webcam.  Tomorrow it is an ESP32-CAM
# streaming MJPEG over WiFi.  Nothing downstream should care which — it
# depends only on the FrameSource protocol below.  Swapping the two is a
# one-line config change (CAMERA_SOURCE), never a code change in the
# follower, verifier, or demo.
# ---------------------------------------------------------------

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from ml.camera import FrameGrabber
from ml.config import CAMERA_INDEX, ESP32_STREAM_URL


@dataclass(frozen=True)
class FrameMeta:
    """
    The identity of a single captured frame.

    seq : int
        Monotonic, strictly increasing per source.  The dedupe key: two
        reads with the same seq are the same physical frame.
    ts : float
        Capture time (time.monotonic()) — for latency measurement and for
        spreading kept crops across the real elapsed movement.
    """
    seq: int
    ts: float


@runtime_checkable
class FrameSource(Protocol):
    """Anything that yields identity-stamped frames."""

    def read(self) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMeta]]:
        """(ok, frame, meta).  ok=False means the source is finished."""
        ...

    def frame_size(self) -> Optional[Tuple[int, int]]:
        """(width, height) of the most recent frame, or None if none yet."""
        ...

    def release(self) -> None:
        ...


# ═════════════════════════════════════════════════════════════════
# WEBCAM  (tonight)  — wraps the existing threaded FrameGrabber
# ═════════════════════════════════════════════════════════════════

class WebcamSource:
    """
    A FrameSource backed by ml.camera.FrameGrabber (newest-frame-only,
    DSHOW on Windows).  Adds the seq/ts identity stamp that FrameGrabber
    itself does not expose.

    FrameGrabber.read() already blocks until a genuinely NEW frame exists
    and refuses to hand the same frame back twice, so each successful read
    here corresponds to exactly one fresh capture — we simply number them.
    """

    def __init__(
        self,
        index: int = CAMERA_INDEX,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        self._grabber = FrameGrabber(index, width=width, height=height,
                                     name="verify-cam")
        self._seq = 0

    def read(self) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMeta]]:
        ok, frame = self._grabber.read()
        if not ok or frame is None:
            return False, None, None
        self._seq += 1
        return True, frame, FrameMeta(seq=self._seq, ts=time.monotonic())

    def frame_size(self) -> Optional[Tuple[int, int]]:
        return self._grabber.frame_size()

    def release(self) -> None:
        self._grabber.release()

    def __enter__(self) -> "WebcamSource":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# ═════════════════════════════════════════════════════════════════
# ESP32-CAM  (tomorrow)  — MJPEG/HTTP stream, same newest-frame policy
# ═════════════════════════════════════════════════════════════════

class MJPEGSource:
    """
    A FrameSource that reads an ESP32-CAM MJPEG stream.

    BUILT NOW, TESTED TOMORROW.  It intentionally mirrors FrameGrabber's
    design — a background thread drains the stream continuously and keeps
    only the newest decoded frame — because a WiFi MJPEG stream backlogs
    exactly like a webcam driver's queue does: if the consumer is slower
    than the stream, naive reads replay old frames and the view lags.

    The consumer API is identical to WebcamSource, so the rest of the
    system cannot tell the two apart.
    """

    def __init__(self, url: str = ESP32_STREAM_URL, timeout: float = 5.0) -> None:
        self.url = url
        self._timeout = timeout
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._seq = 0
        self._last_read_seq = 0
        self._stopped = False
        self._error: Optional[str] = None
        self._thread = threading.Thread(target=self._loop, name="esp32-mjpeg",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        # requests is already a project dependency (see requirements.txt).
        try:
            import requests
        except ImportError as e:  # pragma: no cover - requests is required
            with self._cond:
                self._error = f"requests not available: {e}"
                self._stopped = True
                self._cond.notify_all()
            return

        # WiFi MJPEG from an ESP32-CAM drops and stalls routinely.  Rather than
        # die on the first hiccup (which would end the whole demo), reconnect
        # with a short backoff until we are explicitly released.  Each attempt
        # decodes into the SAME single-frame slot, so reconnection costs no
        # extra memory.
        while True:
            with self._cond:
                if self._stopped:
                    break
            try:
                self._stream_once(requests)
            except Exception as e:
                with self._cond:
                    # Record the last error for the UI but keep trying — a
                    # transient drop should self-heal, not stop the lane.
                    self._error = f"MJPEG stream error ({self.url}): {e}"
            with self._cond:
                if self._stopped:
                    break
            time.sleep(0.5)  # backoff before reconnecting

        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def _stream_once(self, requests) -> None:
        """Open the stream and pump newest-frame-only until it ends/drops."""
        resp = requests.get(self.url, stream=True, timeout=self._timeout)
        with self._cond:
            self._error = None  # connected; clear any prior transient error
        buf = b""
        for chunk in resp.iter_content(chunk_size=4096):
            with self._cond:
                if self._stopped:
                    break
            if not chunk:
                continue
            buf += chunk
            # MJPEG frames are concatenated JPEGs: SOI (ffd8) .. EOI (ffd9).
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9")
            if start != -1 and end != -1 and end > start:
                jpg = buf[start:end + 2]
                buf = buf[end + 2:]
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
                if frame is not None:
                    with self._cond:
                        self._frame = frame
                        self._seq += 1
                        self._cond.notify_all()
            # Guard against unbounded growth if EOI never arrives (corrupt
            # stream): keep only a bounded tail so RAM can't creep on the Pi.
            elif len(buf) > 1_000_000:
                buf = buf[-4096:]

    def read(self, timeout: float = 2.0) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMeta]]:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._frame is None or self._seq == self._last_read_seq:
                if self._stopped:
                    return False, None, None
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False, None, None
                self._cond.wait(remaining)
            self._last_read_seq = self._seq
            return True, self._frame, FrameMeta(seq=self._seq, ts=time.monotonic())

    def frame_size(self) -> Optional[Tuple[int, int]]:
        with self._cond:
            if self._frame is None:
                return None
            h, w = self._frame.shape[:2]
        return (w, h)

    @property
    def error(self) -> Optional[str]:
        with self._cond:
            return self._error

    @property
    def stopped(self) -> bool:
        """True only when permanently finished (released) — NOT during a
        transient reconnect.  Lets a consumer tell 'wait, it'll come back'
        from 'it's over'."""
        with self._cond:
            return self._stopped

    def release(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def __enter__(self) -> "MJPEGSource":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# ═════════════════════════════════════════════════════════════════
# FACTORY
# ═════════════════════════════════════════════════════════════════

def make_frame_source(
    source: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> FrameSource:
    """
    Build the FrameSource named by config.CAMERA_SOURCE.

      "webcam" -> WebcamSource (tonight, laptop)
      "mjpeg"  -> MJPEGSource  (tomorrow, ESP32-CAM)

    Kept tiny and explicit so switching cameras is a config edit, not a
    code change anywhere downstream.
    """
    s = (source or "webcam").lower()
    if s == "mjpeg":
        return MJPEGSource()
    if s == "webcam":
        return WebcamSource(width=width, height=height)
    raise ValueError(f"Unknown CAMERA_SOURCE {source!r} (expected 'webcam' or 'mjpeg').")
