"""Threshold sweep for semantic cache benchmark.

For each mode (t_hit value), this script:
  1. Switches the server to that mode via /v1/admin/mode
  2. Clears the Qdrant semantic cache collection
  3. Runs evaluate_cache_benchmark.py to warm cache and test variants
  4. Tags the output with the mode name

Results land in eval/cache_benchmark_results_<mode>_<timestamp>.json/.csv

Usage:
  python scripts/run_threshold_sweep.py
  python scripts/run_threshold_sweep.py --base-url http://127.0.0.1:8080
  python scripts/run_threshold_sweep.py --modes loose moderate balanced conservative strict
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]

SWEEP_MODES = [
    ("loose",        0.80),
    ("moderate",     0.85),
    ("performance",  0.88),
    ("balanced",     0.90),
    ("conservative", 0.93),
    ("strict",       0.95),
]

QDRANT_URL = "http://localhost:6333"
CACHE_COLLECTION = "acl_semantic_cache_v2"


def switch_mode(base_url: str, mode: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{base_url}/v1/admin/mode",
            json={"mode": mode, "ttl_seconds": 3600},
        )
        resp.raise_for_status()
    print(f"  Switched server to mode={mode}")


def clear_cache() -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{QDRANT_URL}/collections/{CACHE_COLLECTION}/points/delete",
            json={"filter": {}},
        )
        resp.raise_for_status()
    print(f"  Cleared Qdrant collection '{CACHE_COLLECTION}'")


def run_benchmark(base_url: str, mode: str, t_hit: float) -> dict:
    script = REPO_ROOT / "scripts" / "evaluate_cache_benchmark.py"
    result = subprocess.run(
        [
            sys.executable, str(script),
            "--base-url", base_url,
            "--t-hit", str(t_hit),
            "--tag", mode,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: benchmark failed\n{result.stderr}")
        return {}
    # Read the canonical output file rather than parsing mixed stdout
    out_file = REPO_ROOT / "eval" / "cache_benchmark_results.json"
    try:
        data = json.loads(out_file.read_text(encoding="utf-8"))
        return data.get("summary", {})
    except Exception as exc:
        print(f"  WARNING: could not read benchmark output file: {exc}")
        return {}


def print_sweep_table(sweep_results: list[tuple[str, float, dict]]) -> None:
    print("\n" + "=" * 80)
    print(f"{'Mode':<14} {'t_hit':>6} {'hit_rate':>10} {'precision':>10} {'nm_acc_inc':>12} {'nm_acc_elev':>12}")
    print("-" * 80)
    for mode, t_hit, summary in sweep_results:
        if not summary:
            print(f"{mode:<14} {t_hit:>6.2f}  {'ERROR':>10}")
            continue
        by_type = summary.get("by_variant_type", {})
        nm_inc_acc = by_type.get("near_miss_incident", {}).get("accuracy", float("nan"))
        nm_elev_acc = by_type.get("near_miss_elevated_conf", {}).get("accuracy", float("nan"))
        print(
            f"{mode:<14} {t_hit:>6.2f}"
            f"  {summary.get('cache_hit_rate', 0):>9.3f}"
            f"  {summary.get('cache_precision', 0):>9.3f}"
            f"  {nm_inc_acc:>11.3f}"
            f"  {nm_elev_acc:>11.3f}"
        )
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="Threshold sweep for semantic cache benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--modes", nargs="+",
        default=[m for m, _ in SWEEP_MODES],
        choices=[m for m, _ in SWEEP_MODES],
        help="Subset of modes to sweep (default: all)",
    )
    parser.add_argument("--pause", type=float, default=2.0, help="Seconds to wait after mode switch")
    args = parser.parse_args()

    mode_t_hit = {m: t for m, t in SWEEP_MODES}
    selected = [(m, mode_t_hit[m]) for m in args.modes]

    sweep_results: list[tuple[str, float, dict]] = []

    for mode, t_hit in selected:
        print(f"\n[{mode}] t_hit={t_hit}")
        try:
            switch_mode(args.base_url, mode)
        except Exception as exc:
            print(f"  Failed to switch mode: {exc}")
            sweep_results.append((mode, t_hit, {}))
            continue

        time.sleep(args.pause)

        try:
            clear_cache()
        except Exception as exc:
            print(f"  Failed to clear cache: {exc}")
            sweep_results.append((mode, t_hit, {}))
            continue

        print(f"  Running benchmark...")
        summary = run_benchmark(args.base_url, mode, t_hit)
        sweep_results.append((mode, t_hit, summary))
        hit_rate = summary.get("cache_hit_rate")
        precision = summary.get("cache_precision")
        print(f"  Done: cache_hit_rate={hit_rate:.3f}, precision={precision:.3f}"
              if hit_rate is not None else "  Done: no results")

    print_sweep_table(sweep_results)

    # Write consolidated sweep summary
    out_path = REPO_ROOT / "eval" / "threshold_sweep_summary.json"
    out_path.write_text(
        json.dumps(
            [{"mode": m, "t_hit": t, "summary": s} for m, t, s in sweep_results],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nConsolidated summary written to {out_path}")


if __name__ == "__main__":
    main()
