# ---------------------------------------------------------------
# ml/cart_state.py  --  THE CART RECONCILER
#
# THE KEY IDEA
# ─────────────
# The cart is NOT an event log.  There is no add() / remove() that we call
# and hope stays consistent.  Instead the cart is a pure PROJECTION of the
# tracks:
#
#     cart = count of product_id  for every track that is currently
#            "counted" (locked identity, not yet REMOVED)
#
# We recompute this projection from scratch whenever anything changes.
# Because it is derived, it can never drift out of sync with reality: if a
# track is OCCLUDED or LOST it still counts (the item is presumed still
# physically there); only a track that has reached REMOVED (a confirmed
# physical exit) drops out.
#
# This is what makes "low confidence / occlusion / a dropped track never
# removes an item" true BY CONSTRUCTION rather than by careful bookkeeping.
# ---------------------------------------------------------------

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional

from ml.matcher import EmbeddingDB
from ml.track import Track, TrackState


def reconcile(tracks: Iterable[Track]) -> Dict[str, int]:
    """
    Derive the current cart contents from the tracks.

    Returns
    -------
    dict {product_id: quantity}
        One entry per distinct product, quantity = number of counted
        tracks of that product.  Empty dict = empty cart.
    """
    counts: Counter = Counter()
    for t in tracks:
        if t.is_counted():
            counts[t.product_id] += 1
    return dict(counts)


def cart_lines(tracks: Iterable[Track]) -> List[dict]:
    """
    Same projection as reconcile(), but as a display-friendly list that
    also reports HOW each item is currently held (so the UI can show, e.g.,
    'chawal x1 (occluded)').  Sorted by product name for stable rendering.
    """
    by_product: Dict[str, List[Track]] = {}
    for t in tracks:
        if t.is_counted():
            by_product.setdefault(t.product_id, []).append(t)

    lines: List[dict] = []
    for name in sorted(by_product):
        members = by_product[name]
        states = Counter(m.state for m in members)
        lines.append({
            "name": name,
            "qty": len(members),
            "states": dict(states),
            # a compact note if any member is not simply PRESENT/CONFIRMED
            "note": _hold_note(states),
        })
    return lines


def _hold_note(states: Counter) -> str:
    hidden = states.get(TrackState.OCCLUDED, 0) + states.get(TrackState.LOST, 0)
    leaving = states.get(TrackState.MOVING, 0) + states.get(TrackState.EXITING, 0)
    if hidden and not leaving:
        return "hidden"
    if leaving:
        return "leaving"
    return ""


def cart_only_db(tracks: Iterable[Track], full_db: Optional[EmbeddingDB]) -> Optional[EmbeddingDB]:
    """
    Build a database filtered to just the products currently in the cart.

    This mirrors the old get_cart_db(): during a REMOVE / exit check the
    recognizer only has to compare against the handful of items actually
    present, which is faster and avoids hallucinating items that were never
    in the cart.  Returns None if the cart is empty or there is no DB.
    """
    if not full_db:
        return None
    names = set(reconcile(tracks).keys())
    if not names:
        return None
    filtered = {k: v for k, v in full_db.items() if k in names}
    return filtered or None
