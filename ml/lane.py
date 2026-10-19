# ---------------------------------------------------------------
# ml/lane.py  --  THE WHOLE CAMERA MODULE AS ONE OBJECT
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# Everything else in ml/ is a part: the follower follows, the verifier judges
# one item, custody binds one scan to one add.  But the cart backend wants ONE
# thing it can drive with ONE call and read a cart + bill back from.  That is
# LaneController: feed it frames, it returns the cart events (add / remove /
# flag) and keeps a running CartLedger.  It is the seam your real backend plugs
# into — see DEPLOYMENT.md section 8.
#
# WHAT IT ADDS OVER CustodyController
# ─────────────────────────────────────
#   • a CartLedger — the running basket + subtotal (adds on MATCH),
#   • AUTO REMOVAL — a weight DROP (no re-scan) takes an item back out, matched
#     by the recorded unit weight and, when two cart lines share that weight,
#     disambiguated by the camera (flagging, never guessing, when unsure).
#
# HOW IT STAYS CHEAP ON THE PI
# ──────────────────────────────
# It runs the detector EXACTLY ONCE per frame and feeds those detections to
# BOTH the add path (custody, via a push-detector adapter so custody does not
# detect again) and a tiny bounded rolling buffer of the leaving item's crops
# used by the removal path.  CustodyController itself is UNCHANGED — the add
# logic, its guards, and its tests are untouched; this class only wraps it and
# routes events to it.
# ---------------------------------------------------------------

from __future__ import annotations

import time
from collections import deque
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from ml.cart import CartEvent, CartFlag, CartLedger
from ml.config import (
    IMAGE_SIZE,
    REMOVAL_BURST_FRAMES,
    REMOVAL_CLASSIFY_MARGIN,
    REMOVAL_MIN_DROP_G,
    REMOVAL_WEIGHT_TOL_G,
    VERIFY_TXN_TIMEOUT_SEC,
)
from ml.custody import CustodyController
from ml.detector import BackgroundSubtractorDetector, Detection, Detector
from ml.events import BarcodeSource, WeightPhase, WeightSource
from ml.verifier import ProductVerifier, Verdict, VerdictResult
from ml.visibility import assess


def _spread(items: list, k: int) -> list:
    """At most k items spread evenly across the list (keeps both ends).

    Same policy the follower uses for its crop buffer: when we have more views
    than we need, keep coverage of the WHOLE movement rather than the newest
    few, so a removal is judged on the item's travel, not one blurred instant.
    """
    n = len(items)
    if n <= k:
        return list(items)
    if k <= 1:
        return [items[-1]] if n else []
    idx = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    return [items[i] for i in idx]


# ═════════════════════════════════════════════════════════════════
# tiny adapters so LaneController owns the sources and detector
# ═════════════════════════════════════════════════════════════════

class _PushDetector:
    """
    A Detector whose detections are PUSHED in, not computed.  LaneController
    runs the real detector once per frame and set()s the result here, so the
    CustodyController it wraps reuses those detections instead of detecting a
    second time (one detect() per frame on the Pi, not two).
    """

    def __init__(self) -> None:
        self._dets: List[Detection] = []

    def set(self, dets: List[Detection]) -> None:
        self._dets = dets

    def detect(self, frame: np.ndarray) -> List[Detection]:
        return self._dets

    def reset(self) -> None:
        self._dets = []

    def background_image(self) -> Optional[np.ndarray]:
        return None


class _QueueSource:
    """A barcode/weight source LaneController feeds; custody poll()s it."""

    def __init__(self) -> None:
        self._q: deque = deque()

    def push(self, evt) -> None:
        self._q.append(evt)

    def poll(self):
        return self._q.popleft() if self._q else None


class LaneController:
    """
    One object the backend drives for the whole lane.

        lane = LaneController(recognizer=recog, appearance_db=recog.db,
                              colour_db=load_colour_db(), barcode=..., weight=...,
                              prices=load_prices(), frame_size=(640, 480))
        for each frame:
            events = lane.process(frame, meta)   # list[CartEvent], usually empty
            # react to events; render lane.ledger.lines() + lane.ledger.subtotal()

    `process()` returns the CartEvents produced THIS frame:
      • a MATCH add  -> CartEvent(kind="add")
      • a SUSPECT / MISMATCH / UNAVAILABLE add -> CartEvent(kind="flag") (not added)
      • a weight drop -> CartEvent(kind="remove") or a removal flag
    RETRY produces no event (the shopper simply re-presents the item).
    """

    def __init__(
        self,
        recognizer=None,
        appearance_db: Optional[dict] = None,
        colour_db: Optional[dict] = None,
        barcode: Optional[BarcodeSource] = None,
        weight: Optional[WeightSource] = None,
        detector: Optional[Detector] = None,
        verifier: Optional[ProductVerifier] = None,
        prices: Optional[dict] = None,
        frame_size: Tuple[int, int] = (640, 480),
        on_event: Optional[Callable[[CartEvent], None]] = None,
        timeout_sec: float = VERIFY_TXN_TIMEOUT_SEC,
    ) -> None:
        self.verifier = verifier or ProductVerifier(
            recognizer, appearance_db=appearance_db, colour_db=colour_db)
        self.ledger = CartLedger(prices=prices, on_event=on_event)

        self._real_detector = detector or BackgroundSubtractorDetector()
        self._push = _PushDetector()
        self._barcode = barcode
        self._weight = weight

        # Custody sees adds only: a push-detector (no second detect) and queue
        # sources LaneController feeds with scans + NON-removal weight events.
        self._cust_barcode = _QueueSource()
        self._cust_weight = _QueueSource()
        self.custody = CustodyController(
            self._push, self.verifier, self._cust_barcode, self._cust_weight,
            frame_size=frame_size, timeout_sec=timeout_sec)

        # Bounded rolling buffer of the leaving item's crops for the removal
        # path (downscaled to IMAGE_SIZE; deduped by monotonic seq).
        self._leaving: deque = deque(maxlen=REMOVAL_BURST_FRAMES * 3)
        self._rb_last_seq = -1

        self.last_verdict: Optional[VerdictResult] = None
        self.last_event: Optional[CartEvent] = None

    # ── per-frame entry point ─────────────────────────────────────

    def process(self, frame: np.ndarray, meta) -> List[CartEvent]:
        events: List[CartEvent] = []

        # 1. Detect ONCE; share with custody via the push-detector.
        dets = self._real_detector.detect(frame)
        self._push.set(dets)

        # 2. Route a barcode scan to custody (every scan is an add here).
        if self._barcode is not None:
            scev = self._barcode.poll()
            if scev is not None:
                self._cust_barcode.push(scev)

        # 3. Route a weight event: a settle that LOSES mass is a removal and is
        #    handled here; everything else (changing, or a positive settle)
        #    belongs to the add path and is handed to custody.
        removal_evt = None
        if self._weight is not None:
            wev = self._weight.poll()
            if wev is not None:
                is_drop = (wev.phase == WeightPhase.SETTLED
                           and wev.delta <= -REMOVAL_MIN_DROP_G)
                if is_drop:
                    removal_evt = wev
                else:
                    self._cust_weight.push(wev)

        # 4. Keep the leaving-item buffer fresh from this frame's motion.
        self._update_leaving(dets, frame, meta)

        # 5. Advance the add path; translate any completed verdict to the cart.
        verdict = self.custody.process(frame, meta)
        if verdict is not None:
            self.last_verdict = verdict
            ev = self._apply_verdict(verdict)
            if ev is not None:
                events.append(ev)

        # 6. Resolve a removal signalled this frame.
        if removal_evt is not None:
            events.append(self._apply_removal(removal_evt))

        if events:
            self.last_event = events[-1]
        return events

    # ── add path ──────────────────────────────────────────────────

    def _apply_verdict(self, v: VerdictResult) -> Optional[CartEvent]:
        if v.verdict == Verdict.MATCH:
            return self.ledger.add_unit(v.expected_sku, v.weight_delta, v.txn_id)
        if v.verdict == Verdict.SUSPECT:
            return self.ledger.flag(
                CartFlag.SWAP_SUSPECT, v.reason, sku=v.expected_sku,
                weight_g=v.weight_delta, txn_id=v.txn_id)
        if v.verdict == Verdict.MISMATCH:
            return self.ledger.flag(
                CartFlag.MISMATCH, v.reason, sku=v.expected_sku,
                weight_g=v.weight_delta, txn_id=v.txn_id)
        if v.verdict == Verdict.UNAVAILABLE:
            return self.ledger.flag(
                CartFlag.UNAVAILABLE, v.reason, sku=v.expected_sku,
                txn_id=v.txn_id)
        # RETRY -> no cart change; the shopper just re-presents the item.
        return None

    # ── removal path (weight-primary, camera-disambiguated) ────────

    def _apply_removal(self, wev) -> CartEvent:
        drop = abs(wev.delta)
        txn = getattr(wev, "txn_id", "") or ""
        units = self.ledger.all_units()
        crops = self._leaving_crops()

        # Which cart units could have produced a drop of this size?
        matches = [u for u in units
                   if abs(u.weight_g - drop) <= REMOVAL_WEIGHT_TOL_G]
        distinct = sorted({u.sku for u in matches})

        if not matches:
            return self.ledger.flag(
                CartFlag.UNEXPECTED_REMOVAL,
                f"Weight dropped {drop:.0f} g but no cart item weighs about "
                f"that. Holding for review.",
                weight_g=-drop, txn_id=txn)

        if len(distinct) == 1:
            sku = distinct[0]
            # Camera consistency check: if the leaving item CONFIDENTLY looked
            # like a DIFFERENT cart line than the weight implies, do not de-bill
            # on weight alone — flag the contradiction.
            if crops:
                cls = self.verifier.classify(
                    crops, [u.sku for u in units],
                    margin=REMOVAL_CLASSIFY_MARGIN)
                if cls.confident and cls.best_sku and cls.best_sku != sku:
                    return self.ledger.flag(
                        CartFlag.REMOVAL_MISMATCH,
                        f"Weight matches '{sku}' but the item leaving looked "
                        f"like '{cls.best_sku}'. Holding for review.",
                        sku=sku, weight_g=-drop, txn_id=txn)
            removed = self.ledger.remove_unit(sku, weight_g=drop, txn_id=txn)
            if removed is not None:
                return removed
            # Shouldn't happen (sku came from the cart), but never guess.
            return self.ledger.flag(
                CartFlag.UNEXPECTED_REMOVAL,
                f"Could not remove '{sku}'. Holding for review.",
                sku=sku, weight_g=-drop, txn_id=txn)

        # Several cart lines share this weight -> the camera must say which left.
        if crops:
            cls = self.verifier.classify(crops, distinct,
                                         margin=REMOVAL_CLASSIFY_MARGIN)
            if cls.confident and cls.best_sku in distinct:
                removed = self.ledger.remove_unit(cls.best_sku, weight_g=drop,
                                                  txn_id=txn)
                if removed is not None:
                    return removed
        return self.ledger.flag(
            CartFlag.AMBIGUOUS_REMOVAL,
            f"{len(distinct)} cart items weigh about {drop:.0f} g "
            f"({', '.join(distinct)}) and the camera could not tell which "
            f"left. Holding for review.",
            weight_g=-drop, txn_id=txn)

    # ── leaving-item crop buffer ───────────────────────────────────

    def _update_leaving(self, dets: List[Detection], frame: np.ndarray,
                         meta) -> None:
        """Keep crops of the dominant moving blob, deduped by frame seq."""
        if not dets:
            return
        seq = getattr(meta, "seq", None)
        if seq is not None:
            if seq <= self._rb_last_seq:
                return
            self._rb_last_seq = seq
        largest = max(dets, key=lambda d: d.area)
        crop = largest.crop(frame)
        if crop is None or crop.size == 0 or not assess(crop).usable:
            return
        self._leaving.append(cv2.resize(crop, (IMAGE_SIZE, IMAGE_SIZE)))

    def _leaving_crops(self) -> List[np.ndarray]:
        return _spread(list(self._leaving), REMOVAL_BURST_FRAMES)

    # ── introspection for the UI ──────────────────────────────────

    def reset(self) -> None:
        """Abandon any open add transaction (operator cancel)."""
        self.custody.reset()
        self._leaving.clear()
        self._rb_last_seq = -1

    @property
    def follower(self):
        return self.custody.follower

    @property
    def follow_status(self) -> str:
        return self.custody.follow_status

    @property
    def expected_sku(self) -> Optional[str]:
        return self.custody.expected_sku

    @property
    def txn_id(self) -> Optional[str]:
        return self.custody.txn_id

    @property
    def reached_cart(self) -> bool:
        return self.custody.reached_cart

    @property
    def weight_settled(self) -> bool:
        return self.custody.weight_settled
