# ---------------------------------------------------------------
# ml/multi_frame_vote.py
#
# WHAT IT DOES
# ─────────────
# Taking a single frame from a webcam can be unreliable — motion
# blur, reflections, or partial occlusion can confuse the matcher.
#
# This module captures a short burst of frames (~5) and runs the
# matcher on each one.  Only if at least 3 of 5 frames agree on
# the same product AND the majority result is itself "confident"
# do we return a final confident answer.
#
# This is called "majority voting" — a very simple but effective
# way to smooth out frame-to-frame noise.
# ---------------------------------------------------------------

import time
from collections import Counter
from typing import Optional

import cv2
import numpy as np

from ml.config import (
    AGREE_THRESHOLD,
    CAMERA_INDEX,
    FRAME_INTERVAL_SEC,
    NUM_FRAMES,
)
from ml.matcher import EmbeddingDB, match

# NOTE: extract_embedding is imported LAZILY inside capture_and_vote()
# rather than at module level.  Reason: vote_over_results() below is pure
# counting logic with no model dependency, and the identity tracker imports
# it on every frame.  Keeping the TFLite import out of module scope means
# the tracking / identity / cart layer can be imported and unit-tested on a
# machine with no TFLite runtime installed.  capture_and_vote() behaves
# exactly as before.


def vote_over_results(
    results: list[dict],
    total_frames: Optional[int] = None,
) -> dict:
    """
    Majority-vote over a list of ALREADY-COMPUTED match() results.

    This is the pure, camera-free core of the voting logic.  It is used
    in two places:

      • capture_and_vote() below, which grabs its own burst of frames
        (the original demo.py path), and

      • the identity tracker (ml/identity_tracker.py), which collects one
        match() result per GOOD-visibility frame for a single track and
        then calls this to decide whether to LOCK that track's identity
        (VERIFYING -> CONFIRMED).

    Keeping the counting in one function means both paths agree on exactly
    what "the frames agreed" means, and both honour AGREE_THRESHOLD.

    Parameters
    ----------
    results : list of match() dicts
        Each must have at least "top_name" and "confident" keys.
    total_frames : int, optional
        How many frames were attempted (for reporting).  Defaults to
        len(results).

    Returns
    -------
    dict — same shape capture_and_vote has always returned:
        final_name, confident, vote_count, total_frames, message, last_result
    """
    total = len(results) if total_frames is None else total_frames

    if not results:
        return {
            "final_name": "uncertain",
            "confident": False,
            "vote_count": 0,
            "total_frames": total,
            "message": "Uncertain — no frames captured.",
            "last_result": {},
        }

    # Only frames that were INDIVIDUALLY confident get a vote.
    # An uncertain frame from the matcher does not get to vote.
    confident_names = [r["top_name"] for r in results if r.get("confident")]
    vote_counts: Counter = Counter(confident_names)

    if not vote_counts:
        return {
            "final_name": "uncertain",
            "confident": False,
            "vote_count": 0,
            "total_frames": total,
            "message": "Uncertain — needs a clearer view.",
            "last_result": results[-1],
        }

    winner_name, winner_votes = vote_counts.most_common(1)[0]
    confident = winner_votes >= AGREE_THRESHOLD

    return {
        "final_name": winner_name,
        "confident": confident,
        "vote_count": winner_votes,
        "total_frames": total,
        "message": (
            f"Confident: {winner_name}  ({winner_votes}/{total} frames agreed)"
            if confident else
            "Uncertain — needs a clearer view."
        ),
        "last_result": results[-1],
    }


def capture_and_vote(
    cap: Optional[cv2.VideoCapture] = None,
    db: Optional[EmbeddingDB] = None,
) -> dict:
    """
    Capture a short burst of frames, run the matcher on each, and
    return a majority-voted result.

    Parameters
    ----------
    cap : cv2.VideoCapture, optional
        An already-open camera.  Pass this in from demo.py so we
        don't open/close the camera repeatedly.
        If None, this function opens and closes its own camera.

    db : EmbeddingDB, optional
        Pre-loaded embedding database (speeds things up).

    Returns
    -------
    dict with keys:
        "final_name"    (str)  – agreed product name, or "uncertain"
        "confident"     (bool) – True only if voting threshold met
        "vote_count"    (int)  – how many frames agreed on final_name
        "total_frames"  (int)  – how many frames were captured
        "message"       (str)  – human-readable verdict
        "last_result"   (dict) – the raw match() dict from the last frame
    """
    # Lazy import: only this camera-burst path needs the TFLite model.
    from ml.embedding_extractor import extract_embedding

    own_cap = False
    if cap is None:
        cap = cv2.VideoCapture(CAMERA_INDEX)
        own_cap = True
    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open camera index {CAMERA_INDEX}. "
            "Check CAMERA_INDEX in ml/config.py."
        )

    frame_results: list[dict] = []

    try:
        for i in range(NUM_FRAMES):
            # Give the camera a moment between frames.
            # Without this pause we'd be grabbing near-duplicate frames.
            time.sleep(FRAME_INTERVAL_SEC)

            ok, frame = cap.read()
            if not ok or frame is None:
                print(f"[multi_frame_vote] Warning: failed to read frame {i+1}/{NUM_FRAMES}")
                continue

            embedding = extract_embedding(frame)
            result = match(embedding, db=db)
            frame_results.append(result)

    finally:
        if own_cap:
            cap.release()

    # Delegate the actual counting to the shared, camera-free voter so
    # this burst path and the identity tracker stay in perfect agreement.
    return vote_over_results(frame_results, total_frames=len(frame_results))
