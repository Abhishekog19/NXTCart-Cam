# ---------------------------------------------------------------
# ml/events.py  --  HARDWARE INPUT SEAMS  (barcode + weight)
#
# WHY THIS FILE EXISTS
# ─────────────────────
# Two of the three sensors are not the camera, and tonight NONE of the
# hardware exists — only a laptop.  But the verification logic is defined
# ENTIRELY in terms of two events:
#
#     • a BARCODE scan   -> "the expected SKU is X, under transaction T"
#     • a WEIGHT change  -> "something of mass m was added, and the scale
#                            has now settled" (optionally tagged with T)
#
# Every scan opens a TRANSACTION with an id (T).  The camera stamps that id
# onto its verdict and the weight channel may carry it too, so consecutive
# items cannot be cross-bound: a weight settle that belongs to the previous
# scan (or arrives out of order) is identifiable and can be rejected.  When
# the backend supplies its own transaction id at scan time we use it verbatim;
# otherwise the mock generates one so results always carry an id.
#
# So we hide each behind a tiny protocol and provide a MOCK driver for
# tonight (keyboard / programmatic) and leave a clearly-marked seam where
# the REAL driver drops in tomorrow:
#
#     • barcode -> a USB-HID "keyboard wedge" scanner types the code
#     • weight  -> the Arduino streams load-cell readings over serial, and
#                  sends the change/settle result the Pi consumes
#
# Nothing in custody.py, verifier.py, or the demo knows or cares which
# driver is behind the protocol.  Swapping mock for real is a construction
# change in ONE place (the demo's wiring), never a logic change.
# ---------------------------------------------------------------

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable


# ═════════════════════════════════════════════════════════════════
# BARCODE
# ═════════════════════════════════════════════════════════════════

@dataclass
class ScanEvent:
    """One barcode scan: which SKU, under which transaction, and when."""
    sku: str
    txn_id: str
    ts: float


@runtime_checkable
class BarcodeSource(Protocol):
    def poll(self) -> Optional["ScanEvent"]:
        """Return a freshly scanned item since the last poll, else None."""
        ...


class MockBarcodeSource:
    """
    A barcode scanner you drive by hand.

    The demo calls `scan(sku)` when the operator presses a key; `poll()`
    then returns that scan exactly once as a ScanEvent.  This is the tonight
    stand-in for a USB-HID scanner, whose real driver would instead read the
    digits the scanner "types" and return them from poll().

    A transaction id is attached to every scan: the backend may pass its own
    (`scan(sku, txn_id=...)`); otherwise a monotonic mock id is generated so a
    result always has an id to correlate against.
    """

    def __init__(self, skus: Optional[List[str]] = None) -> None:
        self.skus = list(skus or [])
        self._pending: Optional[ScanEvent] = None
        self._counter = 0

    def scan(self, sku: str, txn_id: Optional[str] = None) -> str:
        """Queue a scan; returns the transaction id used."""
        self._counter += 1
        tid = txn_id or f"mock-txn-{self._counter}"
        self._pending = ScanEvent(sku=sku, txn_id=tid, ts=time.monotonic())
        return tid

    def scan_next(self) -> Optional[str]:
        """Cycle to the next known SKU (demo convenience for a keypress)."""
        if not self.skus:
            return None
        # Rotate so repeated presses walk through the catalogue.
        sku = self.skus.pop(0)
        self.skus.append(sku)
        self.scan(sku)
        return sku

    def poll(self) -> Optional[ScanEvent]:
        evt, self._pending = self._pending, None
        return evt


# ═════════════════════════════════════════════════════════════════
# WEIGHT
# ═════════════════════════════════════════════════════════════════

class WeightPhase:
    """Where the load cell is in the add-an-item cycle."""
    STABLE   = "STABLE"    # sitting still at the current total
    CHANGING = "CHANGING"  # mass is being added right now
    SETTLED  = "SETTLED"   # a change just finished and the scale is still


@dataclass
class WeightEvent:
    phase: str
    grams: float
    delta: float           # change vs. the last stable total (0 unless SETTLED)
    ts: float
    # Optional transaction id the weight change belongs to.  When the backend
    # tags settles with the scan's transaction, custody can reject a settle
    # meant for a different (e.g. previous) item.  None = untagged.
    txn_id: Optional[str] = None


@runtime_checkable
class WeightSource(Protocol):
    def poll(self) -> Optional[WeightEvent]:
        """Return the latest weight event since the last poll, else None."""
        ...


class MockWeightSource:
    """
    A load cell you drive by hand.

    The demo calls `begin_change()` when the operator says "I'm adding the
    item" and `settle(delta_grams)` when it has landed; `poll()` surfaces
    CHANGING then SETTLED so custody's "weight changed AND settled" gate is
    genuinely exercised tonight.

    The real driver reads the Arduino serial line (e.g. "W:1234\\n"),
    detects the change and the settle itself, and emits the same events.
    """

    def __init__(self, start_grams: float = 0.0) -> None:
        self._grams = start_grams
        self._stable_grams = start_grams
        self._queue: List[WeightEvent] = []

    def begin_change(self, txn_id: Optional[str] = None) -> None:
        self._queue.append(WeightEvent(WeightPhase.CHANGING, self._grams, 0.0,
                                       time.monotonic(), txn_id))

    def settle(self, delta_grams: float, txn_id: Optional[str] = None,
               ts: Optional[float] = None) -> None:
        self._grams = self._stable_grams + delta_grams
        evt = WeightEvent(WeightPhase.SETTLED, self._grams, delta_grams,
                          time.monotonic() if ts is None else ts, txn_id)
        self._stable_grams = self._grams
        self._queue.append(evt)

    def poll(self) -> Optional[WeightEvent]:
        if not self._queue:
            return None
        return self._queue.pop(0)
