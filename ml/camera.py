# ---------------------------------------------------------------
# ml/camera.py  --  LIVE FRAMES, NOT A BACKLOG
#
# THE PROBLEM THIS SOLVES
# ────────────────────────
# A webcam driver keeps its own queue of captured frames.  When the
# processing loop is slower than the camera's frame rate, that queue fills
# up and every cap.read() hands back the OLDEST frame still in it.  The
# display then shows video from seconds ago: you move your hand, and the
# window responds long after.
#
# This is DELAY, and it is a different problem from THROUGHPUT.  Making the
# pipeline faster shrinks the delay but never removes it — any residual gap
# between camera rate and loop rate re-accumulates a backlog.
#
# The usual attempted fix does not work:
#
#     cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # silently ignored
#     cap.get(cv2.CAP_PROP_BUFFERSIZE)         # -> -1.0 on DSHOW
#
# The property is advisory; most Windows backends do not implement it.
#
# THE FIX
# ────────
# Read the camera in a background thread that keeps ONLY the newest frame
# and throws the rest away.  The queue is drained continuously by the
# thread instead of accumulating for the consumer, so read() always returns
# something captured microseconds ago no matter how slow the consumer is.
#
# read() also refuses to hand back a frame it has already returned.  That
# matters for more than efficiency: the tracker is a per-frame state
# machine, so processing a duplicate frame would look like a frame in which
# nothing moved — no motion means no detections, which would push tracks
# toward OCCLUDED for no reason.  Instead read() waits briefly for a
# genuinely new frame, which also paces the loop to the camera for free.
#
# WHY DSHOW ON WINDOWS
# ─────────────────────
# Measured on this machine, opening the same camera:
#     cv2.CAP_DSHOW  ->  130 ms
#     cv2.CAP_MSMF   -> 2923 ms
# with identical 34.1 ms reads afterwards.  MSMF is the default, so asking
# for DSHOW explicitly turns a three-second startup stall into nothing.
# ---------------------------------------------------------------

from __future__ import annotations

import sys
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from ml.config import CAMERA_INDEX

# How long read() waits for a fresh frame before reporting failure.  Long
# enough to cover a hiccup at any sane frame rate, short enough that a dead
# camera does not hang the UI.
_READ_TIMEOUT = 2.0

# Consecutive failed reads before we declare the camera dead.  A few failures
# are normal while a device warms up.
_MAX_FAILURES = 60

# Pause after a failed read, so a dead camera does not spin a core.
_FAILURE_SLEEP = 0.01


def _open_capture(index: int, width: Optional[int], height: Optional[int],
                  prefer_dshow: bool) -> Optional[cv2.VideoCapture]:
    """Open the camera, trying the fast Windows backend first."""
    backends = []
    if prefer_dshow and sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
        backends.append(cv2.CAP_DSHOW)
    backends.append(cv2.CAP_ANY)

    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            if width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            if height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            # Ask for a shallow driver queue as well.  It is ignored on DSHOW
            # — which is the whole reason this class exists — but it costs
            # nothing and genuinely helps on backends that honour it.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        cap.release()
    return None


class FrameGrabber:
    """
    A camera that always gives you the newest frame.

    Usage mirrors cv2.VideoCapture closely enough to be a drop-in for a
    display loop:

        with FrameGrabber(width=640, height=480) as cam:
            while True:
                ok, frame = cam.read()
                if not ok:
                    break
                ...

    Differences from cv2.VideoCapture, all deliberate:
      • read() skips any frames captured while you were busy — that is the
        point; you get the present, not the backlog.
      • read() blocks (up to a timeout) rather than returning the same frame
        twice, so a per-frame state machine downstream never sees a duplicate.
      • read() returning False means the camera is finished or unresponsive,
        not "try again immediately".
    """

    def __init__(
        self,
        index: int = CAMERA_INDEX,
        width: Optional[int] = None,
        height: Optional[int] = None,
        prefer_dshow: bool = True,
        name: str = "camera",
    ) -> None:
        cap = _open_capture(index, width, height, prefer_dshow)
        if cap is None:
            raise RuntimeError(f"Cannot open camera {index}.")
        self._cap = cap
        self.index = index

        # _cond guards every field below it.
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._seq = 0             # frames captured
        self._last_read_seq = 0   # newest frame handed to the consumer
        self._dropped = 0         # captured frames never seen by the consumer
        self._failures = 0
        self._stopped = False

        self._thread = threading.Thread(
            target=self._loop, name=f"{name}-grabber", daemon=True)
        self._thread.start()

    # ── background capture ───────────────────────────────────────

    def _loop(self) -> None:
        """Drain the camera forever, keeping only the newest frame."""
        while True:
            with self._cond:
                if self._stopped:
                    return

            ok, frame = self._cap.read()

            if not ok or frame is None:
                with self._cond:
                    self._failures += 1
                    if self._failures >= _MAX_FAILURES:
                        self._stopped = True
                        self._cond.notify_all()
                        return
                time.sleep(_FAILURE_SLEEP)
                continue

            with self._cond:
                self._failures = 0
                # cap.read() allocates a fresh array each call, so rebinding
                # here cannot corrupt a frame the consumer is still using: its
                # reference keeps the old array alive and unmodified.
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()

    # ── consumer API ─────────────────────────────────────────────

    def read(self, timeout: float = _READ_TIMEOUT) -> Tuple[bool, Optional[np.ndarray]]:
        """
        The newest frame not yet returned.

        Blocks until one exists, up to `timeout` seconds.  Returns
        (False, None) if the camera has stopped or went quiet for that long.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._frame is None or self._seq == self._last_read_seq:
                if self._stopped:
                    return False, None
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False, None
                self._cond.wait(remaining)

            # Everything captured between the previous read and this one is
            # skipped on purpose — those frames are stale by definition.
            self._dropped += self._seq - self._last_read_seq - 1
            self._last_read_seq = self._seq
            return True, self._frame

    def frame_size(self) -> Optional[Tuple[int, int]]:
        """(width, height) of the most recent frame, or None if none yet."""
        with self._cond:
            if self._frame is None:
                return None
            h, w = self._frame.shape[:2]
        return (w, h)

    @property
    def dropped(self) -> int:
        """
        How many stale frames have been discarded since startup.

        A healthy number: it is the measure of how much delay would otherwise
        have accumulated.  Zero means the loop is keeping up with the camera
        exactly.
        """
        with self._cond:
            return self._dropped

    @property
    def alive(self) -> bool:
        with self._cond:
            return not self._stopped

    def release(self) -> None:
        """Stop the thread and close the device.  Safe to call twice."""
        with self._cond:
            if self._stopped and self._cap is None:
                return
            self._stopped = True
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ── context manager ──────────────────────────────────────────

    def __enter__(self) -> "FrameGrabber":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
