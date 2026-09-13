# ---------------------------------------------------------------
# compare_backends.py  --  WHICH VERIFIER IS ACTUALLY MORE ACCURATE?
#
# WHY THIS TOOL EXISTS  (read this first)
# ────────────────────────────────────────
# This is the deliverable.  It replays a labelled dataset through every
# backend and prints their error rates side by side, so the choice of who
# judges live items is made from measurements instead of intuition.
#
# Both backends see the IDENTICAL crops in the IDENTICAL order.  That is the
# entire point: any difference in the table is a difference between the
# models, not between two different sets of images.
#
# THE METRIC IS NOT ACCURACY
# ───────────────────────────
# "94% correct" is a useless number for a theft-prevention component, because
# the two ways of being wrong have wildly different costs:
#
#   FAR — FALSE ACCEPT.  A swap was called MATCH.  The theft SUCCEEDS, and
#         nobody ever finds out.  This is the number that matters.
#   FRR — FALSE REJECT.  A genuine item was called MISMATCH or SUSPECT.  An
#         honest shopper is stopped and staff are called.  Expensive, but
#         self-correcting — a human resolves it.
#
# A backend with better headline accuracy but a worse FAR is the WORSE
# backend.  The table below therefore leads with FAR and never prints a bare
# accuracy figure without it.
#
# RETRY is scored separately again: it is neither right nor wrong, it is
# FRICTION.  A backend that answers RETRY to everything has a perfect FAR and
# is completely useless, which is exactly why it needs its own column.
#
# Run:
#   python compare_backends.py --dataset kitchen
#   python compare_backends.py --dataset kitchen --backends local
#   python compare_backends.py --dataset kitchen --model z-ai/glm-5.3-flash
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np

from ml.config import AI_BACKEND_BASE_URL, AI_BACKEND_MODEL, DATASET_DIR
from ml.verifier import Verdict

LABEL_GENUINE = "genuine"
LABEL_SWAP = "swap"

# Verdict order for the confusion matrix (and thus for every printed row).
_VERDICTS = [Verdict.MATCH, Verdict.SUSPECT, Verdict.MISMATCH,
             Verdict.RETRY, Verdict.UNAVAILABLE]


@dataclass
class Case:
    """One labelled transaction loaded from disk."""
    name: str
    expected_sku: str
    label: str                      # ground truth: genuine | swap
    crops: List[np.ndarray] = field(default_factory=list)


@dataclass
class BackendRun:
    """Everything one backend did across the whole dataset."""
    name: str
    verdicts: Dict[str, str] = field(default_factory=dict)   # case -> verdict
    reasons: Dict[str, str] = field(default_factory=dict)
    latencies: List[float] = field(default_factory=list)
    tokens: List[int] = field(default_factory=list)
    errors: int = 0


def load_dataset(root: str) -> List[Case]:
    """Load every labelled transaction directory under `root`."""
    if not os.path.isdir(root):
        print(f"[compare] ERROR: no such dataset directory: {root}")
        print("[compare] Capture one first:  python capture_dataset.py --name NAME")
        sys.exit(1)

    cases: List[Case] = []
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        meta_path = os.path.join(d, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError) as e:
            print(f"[compare] skipping {entry}: unreadable meta.json ({e})")
            continue

        label = meta.get("label")
        if label not in (LABEL_GENUINE, LABEL_SWAP):
            print(f"[compare] skipping {entry}: label is {label!r}")
            continue

        crops = []
        for fn in sorted(os.listdir(d)):
            if fn.startswith("crop_") and fn.endswith(".png"):
                img = cv2.imread(os.path.join(d, fn))
                if img is not None:
                    crops.append(img)
        if not crops:
            print(f"[compare] skipping {entry}: no crops")
            continue

        cases.append(Case(name=entry, expected_sku=meta.get("expected_sku", ""),
                          label=label, crops=crops))
    return cases


def run_backend(backend, cases: List[Case], verbose: bool) -> BackendRun:
    """Score every case with one backend."""
    run = BackendRun(name=backend.name)
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        result = None
        try:
            result = backend.verify(case.expected_sku, case.crops,
                                    follower_broken=False)
            verdict, reason = result.verdict, result.reason
        except Exception as e:
            # A backend that raises is broken, not "wrong" — record it apart
            # from the verdict counts so a crash can never look like caution.
            run.errors += 1
            verdict, reason = "ERROR", f"{type(e).__name__}: {e}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        run.verdicts[case.name] = verdict
        run.reasons[case.name] = reason
        run.latencies.append(elapsed_ms)
        tok = getattr(result, "ai_tokens", 0) if result is not None else 0
        if tok:
            run.tokens.append(tok)

        if verbose:
            mark = _mark(case.label, verdict)
            print(f"    [{i:3d}/{len(cases)}] {mark} {case.label:<8} "
                  f"-> {verdict:<12} {case.name}")
            if verdict in ("ERROR",) or mark == "!!":
                print(f"              {reason[:90]}")
        else:
            print(f"\r    {i}/{len(cases)} ...", end="", flush=True)
    if not verbose:
        print("\r" + " " * 40 + "\r", end="")
    return run


def _mark(label: str, verdict: str) -> str:
    """
    Two characters summarising whether this case went right or wrong.

      !!  false ACCEPT — a swap was let through.  The dangerous failure.
      xx  false REJECT — a genuine item was blocked.
      ..  retry/unavailable — no judgement made.
      ok  correct.
    """
    if verdict == "ERROR":
        return "!!"
    if label == LABEL_SWAP:
        if verdict == Verdict.MATCH:
            return "!!"
        if verdict in (Verdict.MISMATCH, Verdict.SUSPECT):
            return "ok"
        return ".."
    if verdict == Verdict.MATCH:
        return "ok"
    if verdict in (Verdict.MISMATCH, Verdict.SUSPECT):
        return "xx"
    return ".."


def summarise(run: BackendRun, cases: List[Case]) -> dict:
    """Turn raw verdicts into the numbers that actually decide the question."""
    by_name = {c.name: c for c in cases}
    genuine = [c for c in cases if c.label == LABEL_GENUINE]
    swaps = [c for c in cases if c.label == LABEL_SWAP]

    false_accepts = [c.name for c in swaps
                     if run.verdicts.get(c.name) == Verdict.MATCH]
    false_rejects = [c.name for c in genuine
                     if run.verdicts.get(c.name) in (Verdict.MISMATCH,
                                                     Verdict.SUSPECT)]
    caught = [c.name for c in swaps
              if run.verdicts.get(c.name) in (Verdict.MISMATCH, Verdict.SUSPECT)]
    passed = [c.name for c in genuine
              if run.verdicts.get(c.name) == Verdict.MATCH]
    retried = [c.name for c in cases
               if run.verdicts.get(c.name) in (Verdict.RETRY,
                                               Verdict.UNAVAILABLE, "ERROR")]

    # Confusion matrix: label -> verdict -> count.
    matrix = {LABEL_GENUINE: {v: 0 for v in _VERDICTS + ["ERROR"]},
              LABEL_SWAP: {v: 0 for v in _VERDICTS + ["ERROR"]}}
    for c in cases:
        v = run.verdicts.get(c.name)
        if v in matrix[c.label]:
            matrix[c.label][v] += 1

    return {
        "n_genuine": len(genuine),
        "n_swap": len(swaps),
        "far": len(false_accepts) / len(swaps) if swaps else None,
        "frr": len(false_rejects) / len(genuine) if genuine else None,
        "catch_rate": len(caught) / len(swaps) if swaps else None,
        "pass_rate": len(passed) / len(genuine) if genuine else None,
        "retry_rate": len(retried) / len(cases) if cases else None,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "matrix": matrix,
        "mean_latency_ms": (sum(run.latencies) / len(run.latencies)
                            if run.latencies else 0.0),
        "mean_tokens": (sum(run.tokens) / len(run.tokens)
                        if run.tokens else 0),
        "errors": run.errors,
    }


def _pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_report(runs: List[BackendRun], cases: List[Case],
                 price_per_m: Optional[float]) -> None:
    sums = {r.name: summarise(r, cases) for r in runs}
    n_g = sum(1 for c in cases if c.label == LABEL_GENUINE)
    n_s = sum(1 for c in cases if c.label == LABEL_SWAP)

    print("\n" + "=" * 72)
    print("  VERIFIER COMPARISON")
    print(f"  {len(cases)} transactions - {n_g} genuine, {n_s} swap")
    print("=" * 72)

    if n_s == 0 or n_g == 0:
        print("\n  WARNING: the dataset has only ONE label. FAR or FRR cannot")
        print("  be computed, and the comparison below is not meaningful.")
        print("  Capture both genuine AND swap transactions.")

    # ── the headline table ──
    names = [r.name for r in runs]
    w = max(12, max(len(n) for n in names) + 2)
    print(f"\n  {'metric':<26}" + "".join(f"{n:>{w}}" for n in names))
    print("  " + "-" * (26 + w * len(names)))

    def row(label, key, fmt=_pct):
        print(f"  {label:<26}" + "".join(f"{fmt(sums[n][key]):>{w}}"
                                         for n in names))

    print(f"  {'-- SAFETY ' + '-' * 15:<26}")
    row("FAR  (swap accepted)", "far")
    row("catch rate (swap caught)", "catch_rate")
    print(f"  {'-- FRICTION ' + '-' * 13:<26}")
    row("FRR  (genuine blocked)", "frr")
    row("pass rate (genuine ok)", "pass_rate")
    row("retry rate", "retry_rate")
    print(f"  {'-- COST ' + '-' * 17:<26}")
    row("mean latency", "mean_latency_ms",
        lambda x: f"{x:7.1f}ms" if x else "      -")
    row("mean tokens/call", "mean_tokens",
        lambda x: f"{x:7.0f}" if x else "      -")
    if price_per_m:
        for n in names:
            t = sums[n]["mean_tokens"]
            if t:
                per = t * price_per_m / 1_000_000.0
                print(f"  {'est. $/verification':<26}"
                      f"{'$' + format(per, '.6f'):>{w}}  ({n})")
    row("crashes", "errors", lambda x: f"{x:7d}" if x else "      -")

    # ── confusion matrices ──
    for n in names:
        m = sums[n]["matrix"]
        print(f"\n  confusion - {n}")
        print(f"    {'truth':<10}" + "".join(f"{v[:9]:>11}" for v in _VERDICTS))
        for lbl in (LABEL_GENUINE, LABEL_SWAP):
            print(f"    {lbl:<10}" + "".join(f"{m[lbl][v]:>11}"
                                             for v in _VERDICTS))

    # ── the cases that went wrong ──
    for n in names:
        fa, fr = sums[n]["false_accepts"], sums[n]["false_rejects"]
        if fa:
            print(f"\n  !! {n} FALSE ACCEPTS (theft would succeed):")
            for c in fa:
                print(f"       {c}")
        if fr:
            print(f"\n  xx {n} false rejects (honest shopper blocked):")
            for c in fr[:8]:
                print(f"       {c}")
            if len(fr) > 8:
                print(f"       ... and {len(fr) - 8} more")

    # ── do they fail on the SAME cases? ──
    if len(runs) >= 2:
        a, b = runs[0], runs[1]
        a_wrong = {c.name for c in cases
                   if _mark(c.label, a.verdicts.get(c.name, "")) in ("!!", "xx")}
        b_wrong = {c.name for c in cases
                   if _mark(c.label, b.verdicts.get(c.name, "")) in ("!!", "xx")}
        both = a_wrong & b_wrong
        either = a_wrong | b_wrong
        print(f"\n  {'-' * 68}")
        print("  OVERLAP OF FAILURES")
        print(f"    {a.name} wrong: {len(a_wrong)}   "
              f"{b.name} wrong: {len(b_wrong)}   both wrong: {len(both)}")
        if either:
            complementary = len(either) - len(both)
            print(f"    wrong in exactly one: {complementary} of {len(either)}")
            if complementary > len(both):
                print("    -> They fail on DIFFERENT cases. A combined design")
                print("       (escalate the ambiguous ones) would likely beat")
                print("       either alone.")
            else:
                print("    -> They fail on the SAME cases. Escalating from one")
                print("       to the other would add cost without adding much")
                print("       safety; the hard cases are hard for both.")

    # ── what to do about it ──
    print(f"\n  {'-' * 68}")
    print("  READING THIS TABLE")
    print("    FAR is the number that matters. A backend with a better pass")
    print("    rate but a worse FAR is the worse backend - it is letting")
    print("    thefts through to avoid annoying people.")
    if len(cases) < 20:
        print(f"\n    CAUTION: only {len(cases)} cases. With this few, one")
        print("    misclassification moves a rate by several points. Treat")
        print("    these numbers as directional, not conclusive.")
    print("=" * 72 + "\n")


def main():
    ap = argparse.ArgumentParser(
        description="Compare verification backends on a labelled dataset.")
    ap.add_argument("--dataset", required=True,
                    help="dataset name under datasets/, or a path")
    ap.add_argument("--backends", default="local,ai",
                    help="comma-separated: local,ai  (default both)")
    ap.add_argument("--model", default=AI_BACKEND_MODEL,
                    help="vision model id for the ai backend")
    ap.add_argument("--base-url", default=AI_BACKEND_BASE_URL,
                    help="OpenAI-compatible endpoint (Ollama: "
                         "http://localhost:11434/v1)")
    ap.add_argument("--price-per-m", type=float, default=None,
                    help="input $/million tokens, to estimate cost per "
                         "verification (e.g. 0.075)")
    ap.add_argument("--verbose", action="store_true",
                    help="print every case as it is scored")
    args = ap.parse_args()

    root = args.dataset
    if not os.path.isdir(root):
        root = os.path.join(DATASET_DIR, args.dataset)

    cases = load_dataset(root)
    if not cases:
        print(f"[compare] No labelled transactions found in {root}")
        sys.exit(1)
    print(f"[compare] Loaded {len(cases)} transactions from {root}")

    wanted = [b.strip() for b in args.backends.split(",") if b.strip()]
    runs: List[BackendRun] = []

    if "local" in wanted:
        print("\n[compare] Running LOCAL backend (MobileNet + HSV)...")
        try:
            from ml.backends import LocalBackend
            from ml.recognizer import EmbeddingRecognizer
            from ml.verifier import ProductVerifier, load_colour_db
            recog = EmbeddingRecognizer()
            verifier = ProductVerifier(recog, appearance_db=recog.db,
                                       colour_db=load_colour_db())
            runs.append(run_backend(LocalBackend(verifier), cases, args.verbose))
        except Exception as e:
            print(f"[compare] LOCAL backend unavailable: {e}")
            print("[compare] It needs the reference database - run build_db.py.")

    if "ai" in wanted:
        print(f"\n[compare] Running AI backend ({args.model})...")
        print(f"[compare] Endpoint: {args.base_url}")
        from ml.ai_backend import VLMBackend
        backend = VLMBackend(model=args.model, base_url=args.base_url)
        is_local = ("localhost" in args.base_url or "127.0.0.1" in args.base_url)
        if not backend.api_key and not is_local:
            print("[compare] ERROR: no API key. Set OPENROUTER_API_KEY, or "
                  "point --base-url at a local Ollama.")
        else:
            runs.append(run_backend(backend, cases, args.verbose))
            oks = sum(1 for s in backend.stats if s.ok)
            print(f"[compare] AI calls: {oks}/{len(backend.stats)} succeeded")
            bad = [s for s in backend.stats if not s.ok]
            if bad:
                print(f"[compare] First failure: {bad[0].error}")

    if not runs:
        print("[compare] No backend produced results.")
        sys.exit(1)

    print_report(runs, cases, args.price_per_m)


if __name__ == "__main__":
    main()
