# ---------------------------------------------------------------
# run_bakeoff.py  --  THE FOUR-WAY CAMERA x BACKEND BAKE-OFF
#
# WHY THIS TOOL EXISTS  (read this first)
# ────────────────────────────────────────
# Two open questions, and they are entangled:
#
#   1. WHICH CAMERA?   The ESP32-CAM is cheap and wireless but its image
#      quality is poor, and image quality is the whole input to this module.
#      A USB webcam is bulkier and tethered but sees far more detail.
#   2. WHICH VERIFIER?  The local MobileNet + HSV path, or a vision model?
#
# You cannot answer either alone, because a bad camera can make a good
# verifier look useless and a good camera can rescue a mediocre one.  So this
# runs all FOUR combinations and prints them in one table:
#
#     Test 1   ESP32-CAM  +  local ML      (no AI, no network, free)
#     Test 2   ESP32-CAM  +  AI vision model
#     Test 3   Webcam     +  local ML      (no AI, no network, free)
#     Test 4   Webcam     +  AI vision model
#
# HOW CONTROLLED EACH COMPARISON ACTUALLY IS  (this matters — read it)
# ─────────────────────────────────────────────────────────────────────
#   • WITHIN one camera (1 vs 2, and 3 vs 4) the comparison is EXACT: both
#     backends score the identical saved crops in the identical order, so any
#     difference is purely the verifier.
#   • ACROSS cameras (1 vs 3, 2 vs 4) it is NOT exact.  You cannot shoot the
#     same physical instant with two cameras mounted in one place, so the two
#     datasets are different transactions of the same products.  Handling,
#     lighting and luck differ.  Treat a small cross-camera gap as noise; only
#     a large, consistent gap is evidence about the camera.
#
# To keep even that comparison as fair as possible: capture BOTH datasets in
# ONE sitting, same products, same lighting, same handling, same count.
#
# ONE REFERENCE DATABASE PER CAMERA — NON-NEGOTIABLE
# ───────────────────────────────────────────────────
# The local backend compares a live crop against reference photos.  If the
# references were shot on the webcam and the live crops come from the
# ESP32-CAM, genuine items score low because the two are in different image
# domains — and the table would blame the ESP32-CAM for a mistake you made in
# setup.  So each camera gets its own references and its own .pkl, and this
# tool refuses to guess which is which.
#
# Run (see DEPLOYMENT.md §6 for the full procedure):
#   py -3 run_bakeoff.py \
#       --esp32-dataset esp32 --esp32-db embedding_db_esp32.pkl \
#       --webcam-dataset webcam --webcam-db embedding_db_webcam.pkl \
#       --price-per-m 0.075
#
# Only one camera ready?  Pass just that pair; the other two tests are
# reported as SKIPPED rather than silently omitted.
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

from compare_backends import (LABEL_GENUINE, LABEL_SWAP, BackendRun, Case,
                              build_local_backend, load_dataset, run_backend,
                              summarise)
from ml.config import AI_BACKEND_BASE_URL, AI_BACKEND_MODEL, DATASET_DIR


@dataclass
class Cell:
    """One of the four (camera x backend) tests."""
    test_no: int
    camera: str                 # esp32 | webcam
    backend: str                # local | ai
    dataset: Optional[str]
    db: Optional[str]
    run: Optional[BackendRun] = None
    summary: Optional[dict] = None
    skipped: str = ""           # non-empty = why this test did not run
    n_cases: int = 0

    @property
    def label(self) -> str:
        cam = "ESP32-CAM" if self.camera == "esp32" else "Webcam"
        eng = "local ML" if self.backend == "local" else "AI vision"
        return f"{self.test_no}. {cam} + {eng}"

    @property
    def short(self) -> str:
        return f"{self.camera}/{self.backend}"


def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def _run_cell(cell: Cell, cases: List[Case], model: str, base_url: str,
              verbose: bool) -> None:
    """Score one cell, recording WHY it was skipped if it cannot run."""
    if not cases:
        cell.skipped = "no dataset"
        return
    cell.n_cases = len(cases)

    if cell.backend == "local":
        try:
            backend = build_local_backend(cell.db, name=f"{cell.camera}-local")
        except Exception as e:
            # Missing or mis-stamped DB.  Reported as a SKIP, never as a run
            # of all-failures — the latter would look like a terrible camera
            # when it is actually a setup mistake.
            cell.skipped = f"reference DB unusable ({type(e).__name__}: {e})"
            return
    else:
        from ml.ai_backend import VLMBackend
        backend = VLMBackend(model=model, base_url=base_url,
                             name=f"{cell.camera}-ai")
        is_local_host = ("localhost" in base_url or "127.0.0.1" in base_url)
        if not backend.api_key and not is_local_host:
            cell.skipped = "no API key (set OPENROUTER_API_KEY)"
            return

    print(f"\n[bakeoff] Test {cell.test_no}: {cell.label}  "
          f"({len(cases)} cases)")
    cell.run = run_backend(backend, cases, verbose)
    cell.summary = summarise(cell.run, cases)


def rank_cells(cells: List[Cell]) -> List[Cell]:
    """
    Order the finished tests best-first.  This is the function that picks the
    hardware, so it is kept separate from the printing and is covered by
    test_verify.py.

    THE ORDER OF THE KEYS IS THE POLICY:
      1. FAR   - a swap called MATCH means a theft succeeded and nobody knows.
      2. FRR   - a genuine item blocked means an honest shopper is stopped.
                 Expensive, but a human resolves it, so it loses to FAR.
      3. retry - pure friction; a backend that retries everything has a
                 perfect FAR and is useless, so it must cost something here.
      4. local before AI on an exact tie: same safety for no latency, no
         network dependency and no money.

    Cells with no FAR (a dataset missing one of the two labels) are excluded
    by the caller - they cannot be ranked on safety at all.
    """
    def _or_worst(x: Optional[float]) -> float:
        # NOT `x or 1.0`: a PERFECT rate is 0.0, which is falsy, so `or` would
        # swap the best possible score for the worst possible one and rank a
        # flawless backend last.  Naming the winner is this tool's whole job.
        return 1.0 if x is None else x

    order = {"local": 0, "ai": 1}
    return sorted(cells, key=lambda c: (c.summary["far"],
                                        _or_worst(c.summary["frr"]),
                                        _or_worst(c.summary["retry_rate"]),
                                        order[c.backend]))


def print_bakeoff(cells: List[Cell], price_per_m: Optional[float]) -> None:
    ran = [c for c in cells if c.summary is not None]

    print("\n" + "=" * 78)
    print("  FOUR-WAY BAKE-OFF -- CAMERA x VERIFIER")
    print("=" * 78)

    for c in cells:
        if c.skipped:
            print(f"  SKIPPED  {c.label:<28} {c.skipped}")
    if not ran:
        print("\n  Nothing ran. Capture a dataset first:")
        print("    py -3 capture_dataset.py --name esp32 --source mjpeg")
        print("=" * 78)
        return

    # ── the table ──
    w = 13
    hdr = "".join(f"{c.short:>{w}}" for c in ran)
    print(f"\n  {'metric':<24}{hdr}")
    print("  " + "-" * (24 + w * len(ran)))

    def row(label: str, key: str, fmt=_fmt_pct):
        print(f"  {label:<24}" + "".join(f"{fmt(c.summary[key]):>{w}}"
                                        for c in ran))

    print(f"  {'-- SAFETY (decides it) ':<24}")
    row("FAR  (swap accepted)", "far")
    row("catch rate", "catch_rate")
    print(f"  {'-- FRICTION ':<24}")
    row("FRR  (genuine blocked)", "frr")
    row("pass rate", "pass_rate")
    row("retry rate", "retry_rate")
    print(f"  {'-- COST ':<24}")
    row("mean latency", "mean_latency_ms",
        lambda x: f"{x:9.1f}ms" if x else "        -")
    row("mean tokens", "mean_tokens", lambda x: f"{x:9.0f}" if x else "        -")
    row("crashes", "errors", lambda x: f"{x:9d}" if x else "        -")
    print(f"  {'-- DATASET ':<24}")
    row("genuine cases", "n_genuine",
        lambda x: f"{x:9d}" if x is not None else "        -")
    row("swap cases", "n_swap",
        lambda x: f"{x:9d}" if x is not None else "        -")

    if price_per_m:
        print()
        for c in ran:
            t = c.summary["mean_tokens"]
            if t:
                per = t * price_per_m / 1_000_000.0
                print(f"  est. cost/verification  {c.short:<16} ${per:.6f}"
                      f"   (~{int(1 / per):,} per $1)")

    # ── per-camera: does AI beat local on the SAME crops? ──
    print(f"\n  {'-' * 74}")
    print("  BACKEND VERDICT (exact comparison - identical crops)")
    for cam in ("esp32", "webcam"):
        loc = next((c for c in ran if c.camera == cam and c.backend == "local"),
                   None)
        ai = next((c for c in ran if c.camera == cam and c.backend == "ai"),
                  None)
        if loc is None or ai is None:
            continue
        cam_name = "ESP32-CAM" if cam == "esp32" else "Webcam"
        lf, af = loc.summary["far"], ai.summary["far"]
        if lf is None or af is None:
            continue
        print(f"    {cam_name}:  local FAR {_fmt_pct(lf).strip()}  vs  "
              f"AI FAR {_fmt_pct(af).strip()}", end="")
        if af < lf:
            print("   -> AI is SAFER here")
        elif af > lf:
            print("   -> LOCAL is safer here; AI is not worth its latency")
        else:
            print("   -> tie on safety; prefer local (free, ~1000x faster)")

        # Complementary failures = an escalation design is worth building.
        a_wrong = _wrong_set(loc)
        b_wrong = _wrong_set(ai)
        both, either = a_wrong & b_wrong, a_wrong | b_wrong
        if either:
            only_one = len(either) - len(both)
            print(f"      failures: local {len(a_wrong)}, AI {len(b_wrong)}, "
                  f"both {len(both)}, exactly one {only_one}")
            if only_one > len(both):
                print("      -> they fail on DIFFERENT cases: escalating "
                      "SUSPECT to AI would beat either alone")
            else:
                print("      -> they fail on the SAME cases: escalation adds "
                      "cost, not safety")

    # ── per-backend: does the webcam beat the ESP32? ──
    print(f"\n  {'-' * 74}")
    print("  CAMERA VERDICT (approximate - different physical transactions)")
    for eng in ("local", "ai"):
        e = next((c for c in ran if c.camera == "esp32" and c.backend == eng),
                 None)
        w_ = next((c for c in ran if c.camera == "webcam" and c.backend == eng),
                  None)
        if e is None or w_ is None:
            continue
        ef, wf = e.summary["far"], w_.summary["far"]
        if ef is None or wf is None:
            continue
        eng_name = "local ML" if eng == "local" else "AI vision"
        print(f"    with {eng_name}:  ESP32 FAR {_fmt_pct(ef).strip()} / "
              f"FRR {_fmt_pct(e.summary['frr']).strip()}   vs   "
              f"webcam FAR {_fmt_pct(wf).strip()} / "
              f"FRR {_fmt_pct(w_.summary['frr']).strip()}")
        if e.n_cases != w_.n_cases:
            print(f"      NOTE: unequal dataset sizes ({e.n_cases} vs "
                  f"{w_.n_cases}) - not directly comparable")

    # ── the recommendation ──
    print(f"\n  {'-' * 74}")
    print("  RECOMMENDATION")
    scored = [c for c in ran if c.summary["far"] is not None]
    if not scored:
        print("    Cannot rank: no dataset had both genuine AND swap cases.")
    else:
        best = rank_cells(scored)
        win = best[0]
        print(f"    WINNER ON SAFETY:  {win.label}")
        print(f"      FAR {_fmt_pct(win.summary['far']).strip()}  "
              f"FRR {_fmt_pct(win.summary['frr']).strip()}  "
              f"retry {_fmt_pct(win.summary['retry_rate']).strip()}  "
              f"latency {win.summary['mean_latency_ms']:.0f}ms")
        if len(best) > 1:
            print("    Full ranking (FAR, then FRR, then retry):")
            for i, c in enumerate(best, 1):
                print(f"      {i}. {c.label:<26} "
                      f"FAR {_fmt_pct(c.summary['far']).strip():>6}  "
                      f"FRR {_fmt_pct(c.summary['frr']).strip():>6}")

        if win.backend == "ai":
            print("\n    Before committing to AI: it is ~100-1000x slower than")
            print("    the local path and needs a network or a dedicated box.")
            print("    If local FAR is close, prefer local and use AI only to")
            print("    escalate SUSPECT verdicts.")

    smallest = min((c.n_cases for c in ran), default=0)
    if smallest < 20:
        print(f"\n    CAUTION: smallest dataset has {smallest} cases. One")
        print("    misclassification moves a rate by several points. These")
        print("    numbers are directional, not conclusive - capture ~30")
        print("    genuine + ~30 swap per camera before deciding hardware.")
    print("=" * 78 + "\n")


def _wrong_set(cell: Cell) -> set:
    """Case names this cell got WRONG (false accept or false reject)."""
    s = cell.summary or {}
    return set(s.get("false_accepts", [])) | set(s.get("false_rejects", []))


def _resolve(name: Optional[str]) -> Optional[str]:
    """Accept either a dataset name under datasets/ or a direct path."""
    if not name:
        return None
    if os.path.isdir(name):
        return name
    p = os.path.join(DATASET_DIR, name)
    return p if os.path.isdir(p) else None


def main():
    ap = argparse.ArgumentParser(
        description="Run all four camera x verifier tests and rank them.")
    ap.add_argument("--esp32-dataset", default=None,
                    help="dataset captured through the ESP32-CAM "
                         "(name under datasets/, or a path)")
    ap.add_argument("--esp32-db", default=None,
                    help="reference .pkl built from ESP32-CAM photos")
    ap.add_argument("--webcam-dataset", default=None,
                    help="dataset captured through the USB webcam")
    ap.add_argument("--webcam-db", default=None,
                    help="reference .pkl built from webcam photos")
    ap.add_argument("--model", default=AI_BACKEND_MODEL,
                    help="vision model id for the AI tests")
    ap.add_argument("--base-url", default=AI_BACKEND_BASE_URL,
                    help="OpenAI-compatible endpoint (Ollama: "
                         "http://localhost:11434/v1)")
    ap.add_argument("--price-per-m", type=float, default=None,
                    help="input $/million tokens, to estimate cost")
    ap.add_argument("--tests", default="1,2,3,4",
                    help="which tests to run, comma-separated (default all)")
    ap.add_argument("--verbose", action="store_true",
                    help="print every case as it is scored")
    args = ap.parse_args()

    wanted = {int(t.strip()) for t in args.tests.split(",") if t.strip()}

    esp_ds = _resolve(args.esp32_dataset)
    web_ds = _resolve(args.webcam_dataset)
    if args.esp32_dataset and esp_ds is None:
        print(f"[bakeoff] ERROR: no such ESP32 dataset: {args.esp32_dataset}")
        sys.exit(1)
    if args.webcam_dataset and web_ds is None:
        print(f"[bakeoff] ERROR: no such webcam dataset: {args.webcam_dataset}")
        sys.exit(1)

    cells = [
        Cell(1, "esp32", "local", esp_ds, args.esp32_db),
        Cell(2, "esp32", "ai", esp_ds, args.esp32_db),
        Cell(3, "webcam", "local", web_ds, args.webcam_db),
        Cell(4, "webcam", "ai", web_ds, args.webcam_db),
    ]

    # Load each dataset ONCE and share it between that camera's two tests.
    # This is what makes tests 1-vs-2 and 3-vs-4 exact rather than merely
    # similar: both backends are handed the same Case objects, same crops,
    # same order.
    loaded: Dict[str, List[Case]] = {}
    for key, path in (("esp32", esp_ds), ("webcam", web_ds)):
        if path:
            print(f"[bakeoff] Loading {key} dataset from {path}")
            loaded[key] = load_dataset(path)
            n_g = sum(1 for c in loaded[key] if c.label == LABEL_GENUINE)
            n_s = sum(1 for c in loaded[key] if c.label == LABEL_SWAP)
            print(f"[bakeoff]   {len(loaded[key])} cases "
                  f"({n_g} genuine, {n_s} swap)")
        else:
            loaded[key] = []

    for cell in cells:
        if cell.test_no not in wanted:
            cell.skipped = "not requested (--tests)"
            continue
        _run_cell(cell, loaded[cell.camera], args.model, args.base_url,
                  args.verbose)

    print_bakeoff(cells, args.price_per_m)


if __name__ == "__main__":
    main()
