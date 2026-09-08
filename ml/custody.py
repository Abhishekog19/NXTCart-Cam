# ---------------------------------------------------------------
# ml/custody.py  --  ONE SCAN, ONE TRANSACTION, TWO REQUIRED PROOFS
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The verifier can say "these crops look like SKU X".  But a verdict is
# only meaningful if those crops belong to the item of THIS transaction —
# the one the shopper just scanned and just put in the cart.  Custody is
# what binds the three sensors into a single, auditable transaction:
#
#     scan(SKU)  ─┐
#                 ├─ follow the ONE item from scanner → cart  (camera)
#     weight  ────┘   AND require the scale to change then settle
#
# A verdict is produced ONLY when BOTH proofs land for the same scan:
#
#     1. SPATIAL   — the followed item actually reached the cart region.
#     2. WEIGHT    — the load cell changed and settled (mass really landed).
#
# Either alone is not enough:
#     • reached cart but no weight change  -> nothing was really added -> RETRY
#     • weight settled but item never got  -> we never got clean crops of
#       to the cart region                    what landed              -> RETRY
#
# GUARDS THAT PROTECT THE TRANSACTION
# ────────────────────────────────────
#     • timeout            a transaction that never completes resolves RETRY
#                          instead of hanging the lane forever.
#     • second scan        a new scan while one is open ABORTS the open one
#                          (RETRY) and starts fresh — the shopper re-scanned,
#                          so the half-finished transaction is void.
#     • broken follow      ambiguous / merged / lost item -> RETRY (the
#                          follower already refuses to guess; custody just
#                          surfaces it).
#     • stale/mismatched    a weight settle tagged for a DIFFERENT transaction,
#       weight settle       or time-stamped before this scan opened, is DROPPED
#                           — a late settle from the previous item cannot
#                           complete this one, so consecutive items are never
#                           cross-bound.
#
# Every scan opens a transaction with an id; that id (and the settled weight
# delta) is stamped onto the VerdictResult, so downstream fusion can correlate
# a camera result with the exact scan — and reject one that arrives against the
# wrong transaction.
#
# Nothing here can turn ambiguity into acceptance; every uncertain path is
# RETRY, and only a clean MATCH from the verifier accepts.
# ---------------------------------------------------------------

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ml.config import VERIFY_TXN_TIMEOUT_SEC
from ml.detector import Detector
from ml.events import BarcodeSource, WeightPhase, WeightSource
from ml.item_follower import FollowStatus, ItemFollower
from ml.verifier import ProductVerifier, Verdict, VerdictResult


class TxnState:
    IDLE      = "IDLE"       # no open transaction; waiting for a scan
    FOLLOWING = "FOLLOWING"  # scan seen; watching the item travel
    DONE      = "DONE"       # a verdict was produced this frame


@dataclass
class Transaction:
    expected_sku: str
    started_ts: float
    txn_id: str = ""
    reached_cart: bool = False
    weight_settled: bool = False
    weight_delta: float = 0.0


class CustodyController:
    """
    Drives one scan→verify transaction at a time.

    Call process(frame, meta) once per frame.  It pulls any barcode/weight
    events from the injected sources, advances the follower, and — when both
    required proofs are in — runs the verifier and returns a VerdictResult.
    Returns None on frames that do not complete a transaction.
    """

    def __init__(
        self,
        detector: Detector,
        verifier: ProductVerifier,
        barcode: BarcodeSource,
        weight: WeightSource,
        frame_size: Tuple[int, int],
        timeout_sec: float = VERIFY_TXN_TIMEOUT_SEC,
    ) -> None:
        self.detector = detector
        self.verifier = verifier
        self.barcode = barcode
        self.weight = weight
        self.frame_size = frame_size
        self.timeout_sec = timeout_sec

        self.state = TxnState.IDLE
        self.txn: Optional[Transaction] = None
        self.follower: Optional[ItemFollower] = None
        self.last_result: Optional[VerdictResult] = None
        # For the UI: the follower's status this frame.
        self.follow_status: str = FollowStatus.WAITING
        # Fallback transaction-id generator, used only when a scan arrives
        # without a backend-provided id, so every result still carries one.
        self._local_txn_seq = 0

    def _next_local_txn_id(self) -> str:
        self._local_txn_seq += 1
        return f"cam-local-{self._local_txn_seq}"

    # ── per-frame entry point ─────────────────────────────────────

    def process(self, frame: np.ndarray, meta) -> Optional[VerdictResult]:
        # 1. Barcode first — a new scan supersedes any open transaction.  If it
        #    aborted one, surface that RETRY THIS frame (the fresh transaction
        #    opened by the same scan continues on following frames).
        scanned = self.barcode.poll()
        if scanned is not None:
            aborted = self._on_scan(scanned.sku, scanned.txn_id)
            if aborted is not None:
                return aborted

        # 2. Weight events (change / settle) bind to the open transaction — but
        #    ONLY if the settle actually belongs to it.  A settle tagged for a
        #    different transaction, or time-stamped before this scan opened
        #    (a late settle from the previous item), is dropped so consecutive
        #    items can never be cross-bound.
        evt = self.weight.poll()
        if (evt is not None and self.txn is not None
                and evt.phase == WeightPhase.SETTLED):
            evt_txn = getattr(evt, "txn_id", None)
            evt_ts = getattr(evt, "ts", None)
            mismatched = evt_txn is not None and evt_txn != self.txn.txn_id
            stale = evt_ts is not None and evt_ts < self.txn.started_ts
            if not mismatched and not stale:
                self.txn.weight_settled = True
                self.txn.weight_delta = evt.delta

        # 3. No open transaction -> nothing to do.
        if self.state != TxnState.FOLLOWING or self.txn is None or self.follower is None:
            return None

        # 4. Timeout guard.
        if time.monotonic() - self.txn.started_ts > self.timeout_sec:
            return self._resolve(Verdict.RETRY,
                                 "Timed out waiting for the item to reach the "
                                 "cart and the weight to settle. Please re-scan.")

        # 5. Advance the follow with this frame's detections.
        detections = self.detector.detect(frame)
        status = self.follower.update(detections, frame, meta)
        self.follow_status = status

        # 6. Broken chain of custody -> RETRY (follower refused to guess).
        if status in FollowStatus.BROKEN:
            return self._resolve_retry_broken(status)

        if status == FollowStatus.REACHED_CART:
            self.txn.reached_cart = True

        # 7. Both required proofs in -> verify now.
        if self.txn.reached_cart and self.txn.weight_settled:
            crops = self.follower.crops
            result = self.verifier.verify(self.txn.expected_sku, crops,
                                          follower_broken=False)
            return self._finish(result)

        return None

    # ── transaction lifecycle ─────────────────────────────────────

    def _on_scan(self, sku: str, txn_id: Optional[str] = None) -> Optional[VerdictResult]:
        """
        Open a fresh transaction for `sku`.  If one was already open, ABORT it
        first (the shopper re-scanned, so the half-finished one is void) and
        RETURN that abort verdict so the caller can surface it; the new
        transaction is opened regardless and continues on later frames.

        `txn_id` is the backend-provided transaction id; when absent a local
        id is generated so the result always carries one.
        """
        aborted: Optional[VerdictResult] = None
        if self.state == TxnState.FOLLOWING and self.txn is not None:
            aborted = self._resolve(
                Verdict.RETRY,
                "A new item was scanned before the previous one finished. "
                "Previous scan cancelled.")
        self.txn = Transaction(
            expected_sku=sku,
            started_ts=time.monotonic(),
            txn_id=txn_id or self._next_local_txn_id(),
        )
        self.follower = ItemFollower(self.frame_size)
        self.state = TxnState.FOLLOWING
        self.follow_status = FollowStatus.WAITING
        return aborted

    def _resolve_retry_broken(self, status: str) -> VerdictResult:
        reason = {
            FollowStatus.AMBIGUOUS: "Could not tell which item was scanned "
                                    "(too many things moved). Please re-scan.",
            FollowStatus.MERGED:    "The item merged with your hand or another "
                                    "item. Please re-present it.",
            FollowStatus.LOST:      "Lost sight of the item on its way to the "
                                    "cart. Please re-scan.",
        }.get(status, "Lost track of the item. Please re-scan.")
        sku = self.txn.expected_sku if self.txn else ""
        # Route through the verifier so the result shape is identical, but the
        # broken flag forces RETRY regardless of any stray crop content.
        result = self.verifier.verify(sku, [], follower_broken=True)
        result.reason = reason
        return self._finish(result)

    def _resolve(self, verdict: str, reason: str) -> VerdictResult:
        """Force a terminal result for the current transaction (guards)."""
        sku = self.txn.expected_sku if self.txn else ""
        result = VerdictResult(verdict, 0.0, 0.0, 0.0, 0.0, 0, reason, sku)
        return self._finish(result)

    def _finish(self, result: VerdictResult) -> VerdictResult:
        # Stamp the transaction identity and the bound weight change onto the
        # result BEFORE clearing the transaction, so every camera verdict can
        # be correlated to its scan (and its weight) downstream.
        if self.txn is not None:
            result.txn_id = self.txn.txn_id
            result.weight_delta = self.txn.weight_delta
        self.last_result = result
        self.state = TxnState.IDLE
        self.txn = None
        self.follower = None
        return result

    def reset(self) -> None:
        """Abandon any open transaction and return to IDLE (operator reset)."""
        self.state = TxnState.IDLE
        self.txn = None
        self.follower = None
        self.follow_status = FollowStatus.WAITING

    # ── introspection for the UI ──────────────────────────────────

    @property
    def expected_sku(self) -> Optional[str]:
        return self.txn.expected_sku if self.txn else None

    @property
    def txn_id(self) -> Optional[str]:
        return self.txn.txn_id if self.txn else None

    @property
    def reached_cart(self) -> bool:
        return bool(self.txn and self.txn.reached_cart)

    @property
    def weight_settled(self) -> bool:
        return bool(self.txn and self.txn.weight_settled)
