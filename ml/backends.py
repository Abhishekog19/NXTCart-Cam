# ---------------------------------------------------------------
# ml/backends.py  --  TWO VERIFIERS, ONE INTERFACE
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# There is now more than one way to answer the camera's only question:
#
#       "The scanner says SKU X.  Is the item that just went into the
#        cart actually X?"
#
#   1. LOCAL  — MobileNet appearance cosine + HSV colour histogram, scored
#               against absolute thresholds (ml/verifier.py).  Fast (~ms),
#               offline, free, deterministic.
#   2. AI     — a vision-language model looks at the crop and says whether it
#               is the scanned product (ml/ai_backend.py).  Slow (~seconds),
#               needs an endpoint, costs a fraction of a cent, not
#               deterministic.
#
# THE HONEST REASON THIS SEAM EXISTS
# ───────────────────────────────────
# The local path's accuracy has NEVER BEEN MEASURED.  Its thresholds
# (VERIFY_APPEARANCE_THRESHOLD / VERIFY_COLOR_THRESHOLD / VERIFY_PASS_FRACTION)
# are seeded guesses — ml/config.py says so in its own comments.  So we do not
# actually know whether AI would judge these products better or worse.
#
# Guessing is not good enough for the component whose job is catching theft.
# So both implementations are made PEERS behind one protocol, and
# compare_backends.py runs them over the SAME labelled crops and prints the
# error rates side by side.  Whoever wins on the numbers earns the lane.
#
# WHY THE PROTOCOL LOOKS LIKE THIS
# ─────────────────────────────────
# The signature is deliberately IDENTICAL to ProductVerifier.verify(), so:
#   • the existing ProductVerifier already satisfies it with no changes, and
#   • CustodyController can be handed either backend without knowing which,
#     exactly as it already treats barcode/weight hardware behind the
#     protocols in ml/events.py.
#
# Both backends must also return the SAME VerdictResult shape and the SAME
# five verdicts.  That is what makes the comparison apples-to-apples instead
# of two tools measured on two different yardsticks.
# ---------------------------------------------------------------

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

import numpy as np

from ml.verifier import ProductVerifier, VerdictResult


@runtime_checkable
class VerificationBackend(Protocol):
    """
    Anything that can judge "are these crops the expected SKU?".

    `name` is a short label used in comparison tables and logs.

    verify() must NEVER raise for an ordinary operational failure (no network,
    bad response, missing data).  Every failure path has to resolve to a
    non-accepting verdict — RETRY or UNAVAILABLE — because an exception
    escaping into the checkout loop is a crash, and a crash in a theft-
    prevention component is indistinguishable from the component being absent.
    """

    name: str

    def verify(self, expected_sku: str, crops: List[np.ndarray],
               follower_broken: bool = False) -> VerdictResult:
        ...


class LocalBackend:
    """
    The existing MobileNet + HSV verifier, wearing the backend interface.

    This is a thin named wrapper, NOT a reimplementation: it forwards straight
    to ProductVerifier so the production logic under test is the exact same
    code that runs in the lane.  Wrapping it (rather than using
    ProductVerifier directly) buys one thing — a `name` for the comparison
    table — and costs one attribute lookup.
    """

    def __init__(self, verifier: ProductVerifier, name: str = "local") -> None:
        self.verifier = verifier
        self.name = name

    def verify(self, expected_sku: str, crops: List[np.ndarray],
               follower_broken: bool = False) -> VerdictResult:
        return self.verifier.verify(expected_sku, crops,
                                    follower_broken=follower_broken)
