# ---------------------------------------------------------------
# ml/cart.py  --  THE RUNNING CART AND BILL
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# The verifier answers one question per item ("is this the scanned SKU?").
# But a checkout needs the WHOLE basket: which items are in the cart right
# now, how many of each, and what the bill comes to — and it must go DOWN
# again when an item is taken back out.  That running state is exactly the
# piece that used to live in "your backend"; CartLedger is the module's own,
# testable version of it, so the camera flow is complete end to end and a
# real backend can either adopt it or mirror it.
#
# WHAT A UNIT REMEMBERS  (and why)
# ──────────────────────────────────
# Every added unit records the WEIGHT it put on the scale.  That is what makes
# auto removal possible without a re-scan: when the scale later loses mass, the
# drop is matched against the recorded weight of the units in the cart to find
# which line left (ml/lane.py).  No per-SKU weight table to maintain — the cart
# knows what each unit weighed because it watched it go in.
#
# PRICING IS OPTIONAL AND OVERRIDABLE
# ─────────────────────────────────────
# Prices come from prices.json (if present) only so the demo can show a real
# subtotal.  Quantities are the source of truth; a missing price is shown as
# n/a and never raises.  Your backend remains free to own pricing — the ledger
# computes a subtotal purely as a convenience.
# ---------------------------------------------------------------

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ml.config import CART_CURRENCY, PRICES_PATH


class CartFlag:
    """Why the cart could not simply add/remove — surfaced for review."""
    OK                 = "OK"
    SWAP_SUSPECT       = "SWAP_SUSPECT"        # add flagged (SUSPECT) — not added
    MISMATCH           = "MISMATCH"            # add flagged (MISMATCH) — not added
    UNAVAILABLE        = "UNAVAILABLE"         # no reference — cannot judge, not added
    UNEXPECTED_REMOVAL = "UNEXPECTED_REMOVAL"  # weight dropped, no matching cart unit
    AMBIGUOUS_REMOVAL  = "AMBIGUOUS_REMOVAL"   # same-weight lines, camera unsure
    REMOVAL_MISMATCH   = "REMOVAL_MISMATCH"    # weight says A, camera saw B leave


@dataclass
class CartUnit:
    """One physical item in the cart, remembering what it weighed going in."""
    sku: str
    weight_g: float
    txn_id: str = ""
    added_ts: float = 0.0


@dataclass
class CartEvent:
    """
    Something the cart did (or refused to do) this frame.  LaneController
    returns these so a UI / backend can react, and the demo can narrate them.
    """
    kind: str                     # "add" | "remove" | "flag"
    sku: Optional[str]
    qty_delta: int                # +1 add, -1 remove, 0 flag
    weight_g: float               # signed grams (negative on removal)
    flag: str = CartFlag.OK
    reason: str = ""
    txn_id: str = ""


def load_prices(path: Optional[str] = None) -> Dict[str, float]:
    """
    Load {sku: price} from prices.json.  Returns {} (never raises) when the
    file is missing or malformed — the cart then shows quantities with prices
    as n/a, which is a fine degradation and keeps the demo starting cleanly.
    """
    path = path or PRICES_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


class CartLedger:
    """
    The running basket.  Holds units per SKU (each with its add-weight),
    computes a subtotal from an optional price map, and emits a CartEvent for
    every add / remove / flag.

    All mutations go through add_unit / remove_unit / flag, so the on_event
    callback sees a complete, ordered history — the hook a real backend wires
    to its own cart + payment screen.
    """

    def __init__(self, prices: Optional[Dict[str, float]] = None,
                 currency: str = CART_CURRENCY,
                 on_event: Optional[Callable[[CartEvent], None]] = None) -> None:
        self.prices: Dict[str, float] = dict(prices or {})
        self.currency = currency
        self._on_event = on_event
        self._units: Dict[str, List[CartUnit]] = {}
        self.history: List[CartEvent] = []

    # ── mutations ─────────────────────────────────────────────────

    def _emit(self, event: CartEvent) -> CartEvent:
        self.history.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def add_unit(self, sku: str, weight_g: float = 0.0,
                 txn_id: str = "") -> CartEvent:
        """Add one unit of `sku`, remembering the weight it put on the scale."""
        self._units.setdefault(sku, []).append(
            CartUnit(sku=sku, weight_g=float(weight_g), txn_id=txn_id,
                     added_ts=time.monotonic()))
        return self._emit(CartEvent(
            kind="add", sku=sku, qty_delta=1, weight_g=float(weight_g),
            flag=CartFlag.OK, txn_id=txn_id,
            reason=f"Added {sku} ({weight_g:.0f} g)."))

    def remove_unit(self, sku: str, weight_g: Optional[float] = None,
                    txn_id: str = "", reason: str = "") -> Optional[CartEvent]:
        """
        Remove ONE unit of `sku`.  When `weight_g` is given, the unit whose
        recorded weight is closest to it is the one removed (so the cart line
        that actually left is the one de-billed).  Returns the remove CartEvent,
        or None if the SKU is not in the cart (the caller then flags instead of
        silently doing nothing).
        """
        units = self._units.get(sku)
        if not units:
            return None
        if weight_g is None:
            unit = units.pop()
        else:
            idx = min(range(len(units)),
                      key=lambda i: abs(units[i].weight_g - weight_g))
            unit = units.pop(idx)
        if not units:
            self._units.pop(sku, None)
        return self._emit(CartEvent(
            kind="remove", sku=sku, qty_delta=-1, weight_g=-abs(unit.weight_g),
            flag=CartFlag.OK, txn_id=txn_id,
            reason=reason or f"Removed {sku} ({unit.weight_g:.0f} g)."))

    def flag(self, flag: str, reason: str, sku: Optional[str] = None,
             weight_g: float = 0.0, txn_id: str = "") -> CartEvent:
        """Record a thing the cart REFUSED to do (no quantity change)."""
        return self._emit(CartEvent(
            kind="flag", sku=sku, qty_delta=0, weight_g=weight_g,
            flag=flag, reason=reason, txn_id=txn_id))

    # ── projections ───────────────────────────────────────────────

    def all_units(self) -> List[CartUnit]:
        return [u for units in self._units.values() for u in units]

    def units_of(self, sku: str) -> List[CartUnit]:
        return list(self._units.get(sku, []))

    def quantities(self) -> Dict[str, int]:
        return {sku: len(units) for sku, units in self._units.items() if units}

    def is_empty(self) -> bool:
        return not any(self._units.values())

    def price_of(self, sku: str) -> Optional[float]:
        return self.prices.get(sku)

    def subtotal(self) -> float:
        """Sum of price x qty over priced lines; unpriced lines contribute 0."""
        total = 0.0
        for sku, units in self._units.items():
            price = self.prices.get(sku)
            if price is not None:
                total += price * len(units)
        return round(total, 2)

    def has_unpriced(self) -> bool:
        return any(self.prices.get(sku) is None for sku in self._units)

    def lines(self) -> List[dict]:
        """Display-friendly cart lines, sorted by SKU for stable rendering."""
        out: List[dict] = []
        for sku in sorted(self._units):
            units = self._units[sku]
            if not units:
                continue
            price = self.prices.get(sku)
            out.append({
                "sku": sku,
                "qty": len(units),
                "unit_price": price,
                "line_total": (round(price * len(units), 2)
                               if price is not None else None),
            })
        return out
