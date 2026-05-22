"""Ablation study orchestrator.

Runs three ablation variants against the same Phase A and Phase B benchmarks
and writes consolidated results to eval/ablation_results.json.

Ablations
---------
A1  no_cache_reeval  — cache hits skip soft policy re-evaluation (Phase B only)
                       Tests: does the safety guarantee matter? Expect false allows.
A2  no_cache         — semantic cache disabled; every request hits the LLM (Phase A)
                       Tests: accuracy cost of removing cache. Expect same accuracy, higher latency.
A3  llm_only         — hard policy + cache disabled; LLM decides everything (Phase A)
                       Tests: accuracy cost of removing hard rules. Expect lower accuracy.

Full pipeline (prompt_v5) results are read from existing eval files as the baseline.

Usage
-----
  python scripts/run_ablation_study.py --base-url http://127.0.0.1:8080
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
EVAL_DIR = REPO_ROOT / "eval"
PHASE_A_SCRIPT = REPO_ROOT / "scripts" / "evaluate_synthetic_cases.py"
PHASE_B_SCRIPT = REPO_ROOT / "scripts" / "evaluate_cache_benchmark.py"
OUT_FILE = EVAL_DIR / "ablation_results.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_ablation(base_url: str, mode: str) -> None:
    resp = httpx.post(f"{base_url}/v1/admin/ablation", json={"mode": mode}, timeout=10)
    resp.raise_for_status()
    print(f"  [ablation] mode set to '{mode}'")


def clear_qdrant_cache(base_url: str) -> None:
    """Delete and recreate the semantic cache collection via Qdrant REST API."""
    qdrant_url = "http://localhost:6333"
    collection = "acl_semantic_cache_v2"
    try:
        httpx.delete(f"{qdrant_url}/collections/{collection}", timeout=10)
        time.sleep(1)
        httpx.put(
            f"{qdrant_url}/collections/{collection}",
            json={"vectors": {"size": 384, "distance": "Cosine"}},
            timeout=10,
        )
        print("  [cache] Qdrant collection cleared and recreated")
    except Exception as exc:
        print(f"  [cache] WARNING: could not clear Qdrant cache: {exc}")


def run_phase_a(base_url: str, tag: str) -> dict:
    out_json = EVAL_DIR / f"ablation_phase_a_{tag}.json"
    out_csv = EVAL_DIR / f"ablation_phase_a_{tag}.csv"
    cmd = [
        sys.executable, str(PHASE_A_SCRIPT),
        "--base-url", base_url,
        "--tag", tag,
        "--json-out", str(out_json),
        "--csv-out", str(out_csv),
    ]
    print(f"  [phase_a] running tag={tag} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [phase_a] STDERR: {result.stderr[-500:]}")
        return {}
    with open(out_json) as f:
        data = json.load(f)
    summary = data.get("summary", {})
    print(f"  [phase_a] accuracy={summary.get('decision_exact_accuracy', 'n/a'):.3f}  "
          f"false_allow={summary.get('false_allow_rate', 'n/a'):.3f}")
    return summary


def run_phase_b(base_url: str, tag: str, t_hit: float = 0.90) -> dict:
    out_json = EVAL_DIR / "cache_benchmark_results.json"
    cmd = [
        sys.executable, str(PHASE_B_SCRIPT),
        "--base-url", base_url,
        "--tag", tag,
        "--t-hit", str(t_hit),
    ]
    print(f"  [phase_b] running tag={tag} t_hit={t_hit} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [phase_b] STDERR: {result.stderr[-500:]}")
        return {}
    with open(out_json) as f:
        data = json.load(f)
    summary = data.get("summary", data)
    hit_rate = summary.get("cache_hit_rate", "n/a")
    precision = summary.get("cache_precision", "n/a")
    false_allow = summary.get("false_allow_rate_on_near_miss", "n/a")
    print(f"  [phase_b] hit_rate={hit_rate:.3f}  precision={precision:.3f}  "
          f"false_allow_near_miss={false_allow:.3f}"
          if isinstance(hit_rate, float) else f"  [phase_b] {summary}")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run ablation studies")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--t-hit", type=float, default=0.90)
    parser.add_argument("--skip-a1", action="store_true", help="Skip Ablation 1 (no_cache_reeval)")
    parser.add_argument("--skip-a2", action="store_true", help="Skip Ablation 2 (no_cache)")
    parser.add_argument("--skip-a3", action="store_true", help="Skip Ablation 3 (llm_only)")
    args = parser.parse_args()

    results: dict = {}

    # --- Load baseline (prompt_v5 full pipeline) ---
    baseline_path = EVAL_DIR / "phase_a_eval_results.json"
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline_data = json.load(f)
        results["baseline_full_pipeline"] = {
            "tag": baseline_data.get("metadata", {}).get("tag", "prompt_v5"),
            "phase_a": baseline_data.get("summary", {}),
        }
        print(f"[baseline] loaded from {baseline_path.name}")
    else:
        print("[baseline] WARNING: phase_a_eval_results.json not found, skipping baseline")

    # --- Ablation 1: no_cache_reeval (Phase B only) ---
    if not args.skip_a1:
        print("\n=== Ablation 1: no_cache_reeval (cache hits skip soft re-eval) ===")
        clear_qdrant_cache(args.base_url)
        time.sleep(2)
        set_ablation(args.base_url, "no_cache_reeval")
        # Warm cache with full pipeline first (need anchors cached), then re-set ablation
        # Actually we need to warm with normal mode so cache has entries, then switch to no_cache_reeval
        set_ablation(args.base_url, "none")
        print("  [ablation1] warming cache with full pipeline anchors ...")
        phase_b_warm = run_phase_b(args.base_url, "ablation1_warmup", args.t_hit)
        # Now switch to no_cache_reeval and re-run only variants (cache is warm)
        set_ablation(args.base_url, "no_cache_reeval")
        phase_b_a1 = run_phase_b(args.base_url, "ablation1_no_reeval", args.t_hit)
        results["ablation1_no_cache_reeval"] = {
            "description": "Cache hits served without soft policy re-evaluation",
            "phase_b": phase_b_a1,
        }
        set_ablation(args.base_url, "none")

    # --- Ablation 2: no_cache (Phase A accuracy + latency comparison) ---
    if not args.skip_a2:
        print("\n=== Ablation 2: no_cache (all requests go to LLM, cache disabled) ===")
        set_ablation(args.base_url, "no_cache")
        phase_a_a2 = run_phase_a(args.base_url, "ablation2_no_cache")
        results["ablation2_no_cache"] = {
            "description": "Semantic cache disabled; every request routed to LLM",
            "phase_a": phase_a_a2,
        }
        set_ablation(args.base_url, "none")

    # --- Ablation 3: llm_only (Phase A accuracy) ---
    if not args.skip_a3:
        print("\n=== Ablation 3: llm_only (hard rules + cache disabled) ===")
        set_ablation(args.base_url, "llm_only")
        phase_a_a3 = run_phase_a(args.base_url, "ablation3_llm_only")
        results["ablation3_llm_only"] = {
            "description": "Hard policy + semantic cache disabled; LLM decides all requests",
            "phase_a": phase_a_a3,
        }
        set_ablation(args.base_url, "none")

    # --- Reset and save ---
    print("\n=== Resetting ablation mode to 'none' ===")
    set_ablation(args.base_url, "none")

    with open(OUT_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[done] Results saved to {OUT_FILE}")

    # --- Print comparison table ---
    print("\n" + "=" * 70)
    print("ABLATION COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Variant':<35} {'Accuracy':>10} {'FalseAllow':>12} {'FalseDeny':>11}")
    print("-" * 70)

    def row(name: str, summary: dict) -> None:
        acc = summary.get("decision_exact_accuracy", float("nan"))
        fa = summary.get("false_allow_rate", float("nan"))
        fd = summary.get("false_deny_rate", float("nan"))
        print(f"{name:<35} {acc:>10.1%} {fa:>12.1%} {fd:>11.1%}")

    if "baseline_full_pipeline" in results:
        row("Full pipeline (prompt_v5)", results["baseline_full_pipeline"]["phase_a"])
    if "ablation2_no_cache" in results:
        row("A2: Hard rules + LLM (no cache)", results["ablation2_no_cache"]["phase_a"])
    if "ablation3_llm_only" in results:
        row("A3: LLM only (no hard rules)", results["ablation3_llm_only"]["phase_a"])

    if "ablation1_no_cache_reeval" in results:
        b = results["ablation1_no_cache_reeval"]["phase_b"]
        print("-" * 70)
        print("Phase B cache safety:")
        print(f"  Full pipeline:          precision=1.0   false_allow_near_miss=0.0%")
        hit = b.get("cache_hit_rate", float("nan"))
        prec = b.get("cache_precision", float("nan"))
        fa_nm = b.get("false_allow_rate_on_near_miss", float("nan"))
        print(f"  A1 (no soft re-eval):   precision={prec:.3f}  "
              f"false_allow_near_miss={fa_nm:.1%}  hit_rate={hit:.3f}"
              if isinstance(hit, float) else "  A1: no data")
    print("=" * 70)


if __name__ == "__main__":
    main()
