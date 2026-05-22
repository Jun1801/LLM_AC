"""Evaluate the semantic cache using phase_b_cache_benchmark.jsonl.

Workflow
--------
1. Submit all anchor cases first  → warms the cache with known ALLOW decisions.
2. Submit all variant cases second → measures cache precision and near-miss safety.
3. Write per-case CSV and aggregate JSON.

Threshold sweep
---------------
Run this script at different t_hit values (configured via BALANCED_T_HIT env var and server restart).
Pass --t-hit <value> to record the threshold in the output without affecting the server.
Compare multiple output CSVs to build the Pareto curve (cache hit rate vs. false allow rate).

Usage
-----
  # Start fresh: clear the cache first (restart Qdrant or truncate the collection).
  python scripts/evaluate_cache_benchmark.py --t-hit 0.90 --tag t90

  # Then set BALANCED_T_HIT=0.85 in .env, restart the server, and run again:
  python scripts/evaluate_cache_benchmark.py --t-hit 0.85 --tag t85
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "eval" / "phase_b_cache_benchmark.jsonl"
DEFAULT_JSON_OUT = REPO_ROOT / "eval" / "cache_benchmark_results.json"
DEFAULT_CSV_OUT = REPO_ROOT / "eval" / "cache_benchmark_results.csv"


@dataclass
class CaseResult:
    case_id: str
    phase: str
    anchor_id: str | None
    variant_type: str | None
    expected_decision: str
    actual_decision: str | None
    decision_source: str | None
    is_correct: bool
    cache_hit: bool           # source is "cache" or "validation"
    is_false_allow: bool      # cache hit returned ALLOW when expected was ESCALATE_HUMAN
    error: str | None


_ALLOW_FAMILY = {"ALLOW", "ALLOW_CACHE", "ALLOW_EMERGENCY"}


def decision_correct(actual: str | None, expected: str) -> bool:
    if actual is None:
        return False
    if expected == "ALLOW":
        return actual in _ALLOW_FAMILY
    return actual == expected


def submit(client: httpx.Client, base_url: str, request_dict: dict, timeout: float) -> dict:
    resp = client.post(f"{base_url}/v1/access/decide", json=request_dict, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def evaluate(
    dataset_path: Path,
    base_url: str,
    timeout: float,
) -> list[CaseResult]:
    cases = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    anchors = [c for c in cases if c["phase"] == "anchor"]
    variants = [c for c in cases if c["phase"] == "variant"]

    results: list[CaseResult] = []

    with httpx.Client() as client:
        print(f"Submitting {len(anchors)} anchor cases to warm cache...")
        for case in anchors:
            try:
                resp = submit(client, base_url, case["request"], timeout)
                actual = resp.get("decision")
                source = resp.get("decision_source")
                correct = decision_correct(actual, case["expected_decision"])
                results.append(CaseResult(
                    case_id=case["case_id"],
                    phase="anchor",
                    anchor_id=None,
                    variant_type=None,
                    expected_decision=case["expected_decision"],
                    actual_decision=actual,
                    decision_source=source,
                    is_correct=correct,
                    cache_hit=source in {"cache", "validation"},
                    is_false_allow=False,
                    error=None,
                ))
            except Exception as exc:  # noqa: BLE001
                results.append(CaseResult(
                    case_id=case["case_id"],
                    phase="anchor",
                    anchor_id=None,
                    variant_type=None,
                    expected_decision=case["expected_decision"],
                    actual_decision=None,
                    decision_source=None,
                    is_correct=False,
                    cache_hit=False,
                    is_false_allow=False,
                    error=str(exc),
                ))

        print(f"Submitting {len(variants)} variant cases...")
        for case in variants:
            try:
                resp = submit(client, base_url, case["request"], timeout)
                actual = resp.get("decision")
                source = resp.get("decision_source")
                cache_hit = source in {"cache", "validation"}
                correct = decision_correct(actual, case["expected_decision"])
                # False allow: cache served ALLOW but the correct answer is ESCALATE_HUMAN
                is_false_allow = (
                    cache_hit
                    and actual in {"ALLOW", "ALLOW_CACHE", "ALLOW_EMERGENCY"}
                    and case["expected_decision"] == "ESCALATE_HUMAN"
                )
                results.append(CaseResult(
                    case_id=case["case_id"],
                    phase="variant",
                    anchor_id=case["anchor_id"],
                    variant_type=case["variant_type"],
                    expected_decision=case["expected_decision"],
                    actual_decision=actual,
                    decision_source=source,
                    is_correct=correct,
                    cache_hit=cache_hit,
                    is_false_allow=is_false_allow,
                    error=None,
                ))
            except Exception as exc:  # noqa: BLE001
                results.append(CaseResult(
                    case_id=case["case_id"],
                    phase="variant",
                    anchor_id=case["anchor_id"],
                    variant_type=case["variant_type"],
                    expected_decision=case["expected_decision"],
                    actual_decision=None,
                    decision_source=None,
                    is_correct=False,
                    cache_hit=False,
                    is_false_allow=False,
                    error=str(exc),
                ))

    return results


def compute_summary(results: list[CaseResult], t_hit: float | None, tag: str | None) -> dict:
    variants = [r for r in results if r.phase == "variant"]
    near_miss = [r for r in variants if r.variant_type in {"near_miss_incident", "near_miss_elevated_conf"}]
    safe_variants = [r for r in variants if r.variant_type in {"paraphrase", "artifact_swap"}]

    total_variants = len(variants)
    cache_hits = sum(1 for r in variants if r.cache_hit)
    correct_hits = sum(1 for r in variants if r.cache_hit and r.is_correct)
    false_allows = sum(1 for r in variants if r.is_false_allow)

    cache_hit_rate = cache_hits / total_variants if total_variants else 0.0
    cache_precision = correct_hits / cache_hits if cache_hits else 0.0
    false_allow_rate = false_allows / len(near_miss) if near_miss else 0.0

    by_variant_type: dict[str, dict] = {}
    for vtype in ("paraphrase", "artifact_swap", "near_miss_incident", "near_miss_elevated_conf"):
        group = [r for r in variants if r.variant_type == vtype]
        if not group:
            continue
        g_hits = sum(1 for r in group if r.cache_hit)
        g_false_allows = sum(1 for r in group if r.is_false_allow)
        by_variant_type[vtype] = {
            "count": len(group),
            "cache_hits": g_hits,
            "cache_hit_rate": g_hits / len(group),
            "false_allows": g_false_allows,
            "false_allow_rate": g_false_allows / len(group),
            "accuracy": sum(1 for r in group if r.is_correct) / len(group),
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "t_hit": t_hit,
        "tag": tag,
        "total_cases": len(results),
        "anchor_count": sum(1 for r in results if r.phase == "anchor"),
        "variant_count": total_variants,
        "cache_hit_rate": cache_hit_rate,
        "cache_precision": cache_precision,
        "false_allow_rate_on_near_miss": false_allow_rate,
        "false_allows": false_allows,
        "near_miss_count": len(near_miss),
        "safe_variant_count": len(safe_variants),
        "by_variant_type": by_variant_type,
    }


def write_outputs(
    results: list[CaseResult],
    summary: dict,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"summary": summary, "results": [vars(r) for r in results]}, indent=2),
        encoding="utf-8",
    )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id", "phase", "anchor_id", "variant_type",
        "expected_decision", "actual_decision", "decision_source",
        "is_correct", "cache_hit", "is_false_allow", "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(vars(r))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate semantic cache benchmark")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--t-hit", type=float, default=None, help="Record the t_hit threshold used (informational)")
    parser.add_argument("--tag", default=None, help="Label for this run (e.g. t90, t85)")
    args = parser.parse_args()

    results = evaluate(Path(args.dataset), args.base_url, args.timeout)
    summary = compute_summary(results, args.t_hit, args.tag)

    # Always write canonical outputs
    write_outputs(results, summary, DEFAULT_JSON_OUT, DEFAULT_CSV_OUT)

    # Write timestamped copies for sweep comparison
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    stem = f"_{args.tag}" if args.tag else ""
    write_outputs(
        results,
        summary,
        DEFAULT_JSON_OUT.parent / f"{DEFAULT_JSON_OUT.stem}{stem}_{ts}{DEFAULT_JSON_OUT.suffix}",
        DEFAULT_CSV_OUT.parent / f"{DEFAULT_CSV_OUT.stem}{stem}_{ts}{DEFAULT_CSV_OUT.suffix}",
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
