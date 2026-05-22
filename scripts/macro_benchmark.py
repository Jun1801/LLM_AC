from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from app.mode_manager import MODE_THRESHOLDS
from app.models import Mode

DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_REQUEST_RETRIES = 2

CURRENT_REQUEST_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT_SECONDS
CURRENT_REQUEST_RETRIES = DEFAULT_REQUEST_RETRIES

BENCHMARK_USER = {
    "user_id": "u-macro-bench",
    "role": "analyst",
    "region": "bench",
    "clearance_level": 2,
}

ARTIFACT_SPECS = [
    {"artifact": "quarterly finance report", "department": "finance", "resource_type": "document"},
    {"artifact": "budget forecast workbook", "department": "finance", "resource_type": "document"},
    {"artifact": "expense reconciliation summary", "department": "finance", "resource_type": "document"},
    {"artifact": "vendor contract archive", "department": "legal", "resource_type": "document"},
    {"artifact": "contract renewal checklist", "department": "legal", "resource_type": "document"},
    {"artifact": "policy exception register", "department": "legal", "resource_type": "dataset"},
    {"artifact": "payroll adjustment log", "department": "hr", "resource_type": "dataset"},
    {"artifact": "onboarding handbook", "department": "hr", "resource_type": "document"},
    {"artifact": "headcount planning dashboard", "department": "hr", "resource_type": "dashboard"},
    {"artifact": "incident response report", "department": "security", "resource_type": "document"},
    {"artifact": "security audit log", "department": "security", "resource_type": "dataset"},
    {"artifact": "vulnerability triage board", "department": "security", "resource_type": "dashboard"},
    {"artifact": "deployment readiness checklist", "department": "engineering", "resource_type": "document"},
    {"artifact": "service reliability dashboard", "department": "engineering", "resource_type": "dashboard"},
    {"artifact": "incident retrospective notes", "department": "engineering", "resource_type": "document"},
    {"artifact": "procurement approval ticket", "department": "procurement", "resource_type": "ticket"},
    {"artifact": "supplier risk assessment", "department": "procurement", "resource_type": "document"},
    {"artifact": "inventory variance report", "department": "operations", "resource_type": "report"},
    {"artifact": "warehouse throughput dashboard", "department": "operations", "resource_type": "dashboard"},
    {"artifact": "customer retention dashboard", "department": "marketing", "resource_type": "dashboard"},
    {"artifact": "campaign performance report", "department": "marketing", "resource_type": "report"},
    {"artifact": "compliance checklist", "department": "operations", "resource_type": "document"},
]

PURPOSES_BY_DEPARTMENT = {
    "finance": ["monthly close", "forecast review"],
    "legal": ["contract review", "policy review"],
    "hr": ["staffing review", "onboarding support"],
    "security": ["incident follow-up", "audit preparation"],
    "engineering": ["release planning", "incident follow-up"],
    "procurement": ["vendor review", "approval follow-up"],
    "operations": ["operational planning", "compliance audit"],
    "marketing": ["campaign planning", "performance review"],
}

PROMPT_TEMPLATES = [
    "Need access to {artifact}",
    "Request access to the {artifact}",
    "Need the {artifact} for {purpose}",
    "Please grant access to {artifact} for {purpose}",
    "I need {artifact} access to support {purpose}",
]


@dataclass(frozen=True)
class TracePrompt:
    cluster_id: str
    prompt_id: str
    cluster_rank: int
    department: str
    resource_type: str
    purpose: str
    prompt: str


@dataclass(frozen=True)
class WorkloadEvent:
    sequence: int
    cluster_id: str
    prompt_id: str
    cluster_rank: int
    department: str
    resource_type: str
    purpose: str
    prompt: str
    first_seen_cluster: bool
    cluster_occurrence: int


@dataclass
class RequestSample:
    run_mode: str
    sequence: int
    cluster_id: str
    prompt_id: str
    cluster_rank: int
    cluster_occurrence: int
    first_seen_cluster: bool
    prompt: str
    department: str
    resource_type: str
    wall_ms: float
    app_ms: int
    decision: str
    final_source: str
    route_class: str
    entered_validation_band: bool
    reason_code: str
    confidence: float
    cache_similarity: float | None
    cross_encoder_score: float | None
    estimated_cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class RunSummary:
    run_mode: str
    requests: int
    final_source_counts: dict[str, int]
    route_class_counts: dict[str, int]
    first_seen_requests: int
    repeat_requests: int
    first_seen_route_class_counts: dict[str, int]
    repeat_route_class_counts: dict[str, int]
    wall_avg_ms: float
    wall_p50_ms: float
    wall_p95_ms: float
    app_avg_ms: float
    app_p50_ms: float
    app_p95_ms: float
    cost_total_usd: float
    cost_avg_usd: float
    avg_cache_similarity: float
    avg_cross_encoder_score: float
    prompt_tokens_total: int
    completion_tokens_total: int
    total_tokens_total: int


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def classify_route(final_source: str, cache_similarity: float | None, mode: str) -> tuple[bool, str]:
    thresholds = MODE_THRESHOLDS[Mode(mode)]
    entered_validation_band = cache_similarity is not None and thresholds.t_validate_low <= cache_similarity < thresholds.t_hit
    if final_source == "cache":
        return entered_validation_band, "cache_hit"
    if final_source == "validation":
        return entered_validation_band, "validation_success"
    if final_source == "llm" and entered_validation_band:
        return True, "validation_fallback_llm"
    if final_source == "llm":
        return False, "pure_miss_llm"
    return entered_validation_band, f"other_{final_source}"


def build_trace_catalog(clusters: int = 40, variants_per_cluster: int = 5) -> list[TracePrompt]:
    catalog: list[TracePrompt] = []
    cluster_index = 0
    for spec in ARTIFACT_SPECS:
        for purpose in PURPOSES_BY_DEPARTMENT[spec["department"]]:
            cluster_index += 1
            cluster_id = f"cluster-{cluster_index:03d}"
            for variant_index, template in enumerate(PROMPT_TEMPLATES[:variants_per_cluster], start=1):
                prompt_id = f"{cluster_id}-v{variant_index}"
                prompt = template.format(artifact=spec["artifact"], purpose=purpose)
                catalog.append(
                    TracePrompt(
                        cluster_id=cluster_id,
                        prompt_id=prompt_id,
                        cluster_rank=cluster_index,
                        department=spec["department"],
                        resource_type=spec["resource_type"],
                        purpose=purpose,
                        prompt=prompt,
                    )
                )
            if cluster_index >= clusters:
                return catalog
    return catalog


def group_catalog_by_cluster(catalog: list[TracePrompt]) -> dict[str, list[TracePrompt]]:
    grouped: dict[str, list[TracePrompt]] = {}
    for trace in catalog:
        grouped.setdefault(trace.cluster_id, []).append(trace)
    return grouped


def generate_zipfian_workload(
    catalog: list[TracePrompt],
    workload_size: int,
    zipf_exponent: float,
    seed: int,
) -> list[WorkloadEvent]:
    grouped = group_catalog_by_cluster(catalog)
    cluster_ids = sorted(grouped.keys())
    weights = [1.0 / ((idx + 1) ** zipf_exponent) for idx in range(len(cluster_ids))]
    rng = random.Random(seed)
    sampled_clusters = rng.choices(cluster_ids, weights=weights, k=workload_size)
    seen_counts: Counter[str] = Counter()
    events: list[WorkloadEvent] = []
    for sequence, cluster_id in enumerate(sampled_clusters, start=1):
        variants = grouped[cluster_id]
        trace = rng.choice(variants)
        seen_counts[cluster_id] += 1
        events.append(
            WorkloadEvent(
                sequence=sequence,
                cluster_id=cluster_id,
                prompt_id=trace.prompt_id,
                cluster_rank=trace.cluster_rank,
                department=trace.department,
                resource_type=trace.resource_type,
                purpose=trace.purpose,
                prompt=trace.prompt,
                first_seen_cluster=seen_counts[cluster_id] == 1,
                cluster_occurrence=seen_counts[cluster_id],
            )
        )
    return events


def build_payload(event: WorkloadEvent, run_id: str, run_mode: str) -> dict:
    if run_mode == "cache_enabled":
        department = f"{event.department}-macro-{run_id}-{event.cluster_id}"
        resource_id = f"{event.cluster_id}-macro-{run_id}"
    else:
        department = f"{event.department}-macro-{run_id}-{event.cluster_id}-{event.sequence}"
        resource_id = f"{event.cluster_id}-macro-{run_id}-{event.sequence}"
    return {
        "request_id": f"{run_mode}-{event.sequence}-{uuid4()}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "user": {
            "user_id": BENCHMARK_USER["user_id"],
            "role": BENCHMARK_USER["role"],
            "department": department,
            "region": BENCHMARK_USER["region"],
            "clearance_level": BENCHMARK_USER["clearance_level"],
        },
        "context": {
            "ip_address": "10.99.0.20",
            "device_id": "dev-macro-bench",
            "session_id": "sess-macro-bench",
            "mfa_state": "passed",
            "incident_state": "normal",
        },
        "resource": {
            "resource_type": event.resource_type,
            "resource_id": resource_id,
            "sensitivity": "internal",
        },
        "query": {
            "prompt": event.prompt,
            "purpose": event.purpose,
        },
    }


def ensure_ready(base_url: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        health = client.get(f"{base_url}/health")
        health.raise_for_status()
        ready = client.get(f"{base_url}/ready")
        ready.raise_for_status()
        body = ready.json()
    if body.get("status") != "ready":
        raise RuntimeError(f"service not ready: {json.dumps(body, indent=2)}")


def post_decision(base_url: str, payload: dict) -> dict:
    last_exc: Exception | None = None
    for attempt in range(CURRENT_REQUEST_RETRIES + 1):
        try:
            with httpx.Client(timeout=CURRENT_REQUEST_TIMEOUT_SECONDS) as client:
                start = time.perf_counter()
                response = client.post(f"{base_url}/v1/access/decide", json=payload)
                wall_ms = (time.perf_counter() - start) * 1000
                response.raise_for_status()
                body = response.json()
            return {"body": body, "wall_ms": wall_ms}
        except httpx.ReadTimeout as exc:
            last_exc = exc
            if attempt >= CURRENT_REQUEST_RETRIES:
                raise
            log(
                f"request timeout attempt={attempt + 1}/{CURRENT_REQUEST_RETRIES + 1} "
                f"timeout_seconds={CURRENT_REQUEST_TIMEOUT_SECONDS} request_id={payload.get('request_id')}"
            )
    raise last_exc or RuntimeError("request failed without exception details")


def run_workload(base_url: str, workload: list[WorkloadEvent], run_mode: str, run_id: str) -> list[RequestSample]:
    samples: list[RequestSample] = []
    log(f"{run_mode} start requests={len(workload)}")
    for event in workload:
        payload = build_payload(event, run_id=run_id, run_mode=run_mode)
        result = post_decision(base_url, payload)
        body = result["body"]
        scores = body.get("scores") or {}
        entered_validation_band, route_class = classify_route(
            final_source=body["decision_source"],
            cache_similarity=scores.get("cache_similarity"),
            mode=body["mode"],
        )
        sample = RequestSample(
            run_mode=run_mode,
            sequence=event.sequence,
            cluster_id=event.cluster_id,
            prompt_id=event.prompt_id,
            cluster_rank=event.cluster_rank,
            cluster_occurrence=event.cluster_occurrence,
            first_seen_cluster=event.first_seen_cluster,
            prompt=event.prompt,
            department=event.department,
            resource_type=event.resource_type,
            wall_ms=result["wall_ms"],
            app_ms=int(body["latency_ms"]),
            decision=body["decision"],
            final_source=body["decision_source"],
            route_class=route_class,
            entered_validation_band=entered_validation_band,
            reason_code=body.get("reason_code", ""),
            confidence=float(body.get("confidence", 0.0) or 0.0),
            cache_similarity=scores.get("cache_similarity"),
            cross_encoder_score=scores.get("cross_encoder_score"),
            estimated_cost_usd=float(body.get("estimated_cost_usd", 0.0) or 0.0),
            prompt_tokens=int((body.get("llm_usage") or {}).get("prompt_tokens", 0) or 0),
            completion_tokens=int((body.get("llm_usage") or {}).get("completion_tokens", 0) or 0),
            total_tokens=int((body.get("llm_usage") or {}).get("total_tokens", 0) or 0),
        )
        samples.append(sample)
        if event.sequence <= 5 or event.sequence % 100 == 0 or event.sequence == len(workload):
            log(
                f"{run_mode} progress {event.sequence}/{len(workload)} "
                f"cluster={event.cluster_id} occurrence={event.cluster_occurrence} "
                f"final_source={sample.final_source} route_class={sample.route_class} wall_ms={sample.wall_ms:.2f}"
            )
    log(f"{run_mode} complete")
    return samples


def build_run_summary(run_mode: str, samples: list[RequestSample]) -> RunSummary:
    wall = [sample.wall_ms for sample in samples]
    app = [float(sample.app_ms) for sample in samples]
    cost = [sample.estimated_cost_usd for sample in samples]
    cache_scores = [float(sample.cache_similarity) for sample in samples if sample.cache_similarity is not None]
    cross_scores = [float(sample.cross_encoder_score) for sample in samples if sample.cross_encoder_score is not None]
    first_seen = [sample for sample in samples if sample.first_seen_cluster]
    repeats = [sample for sample in samples if not sample.first_seen_cluster]
    return RunSummary(
        run_mode=run_mode,
        requests=len(samples),
        final_source_counts=dict(Counter(sample.final_source for sample in samples)),
        route_class_counts=dict(Counter(sample.route_class for sample in samples)),
        first_seen_requests=len(first_seen),
        repeat_requests=len(repeats),
        first_seen_route_class_counts=dict(Counter(sample.route_class for sample in first_seen)),
        repeat_route_class_counts=dict(Counter(sample.route_class for sample in repeats)),
        wall_avg_ms=statistics.mean(wall),
        wall_p50_ms=percentile(wall, 50),
        wall_p95_ms=percentile(wall, 95),
        app_avg_ms=statistics.mean(app),
        app_p50_ms=percentile(app, 50),
        app_p95_ms=percentile(app, 95),
        cost_total_usd=sum(cost),
        cost_avg_usd=statistics.mean(cost),
        avg_cache_similarity=statistics.mean(cache_scores) if cache_scores else 0.0,
        avg_cross_encoder_score=statistics.mean(cross_scores) if cross_scores else 0.0,
        prompt_tokens_total=sum(sample.prompt_tokens for sample in samples),
        completion_tokens_total=sum(sample.completion_tokens for sample in samples),
        total_tokens_total=sum(sample.total_tokens for sample in samples),
    )


def build_workload_locality(workload: list[WorkloadEvent]) -> dict[str, object]:
    cluster_counts = Counter(event.cluster_id for event in workload)
    prompt_counts = Counter(event.prompt_id for event in workload)
    total = len(workload)
    top_clusters = [
        {
            "cluster_id": cluster_id,
            "count": count,
            "share": round(count / total, 4),
        }
        for cluster_id, count in cluster_counts.most_common(10)
    ]
    top_cluster_share = sum(item["count"] for item in top_clusters) / total if total else 0.0
    top_10pct = max(1, len(cluster_counts) // 10)
    top_10pct_share = (
        sum(count for _, count in cluster_counts.most_common(top_10pct)) / total if total else 0.0
    )
    return {
        "requests": total,
        "unique_clusters_sampled": len(cluster_counts),
        "unique_prompts_sampled": len(prompt_counts),
        "top_cluster_share": round(top_cluster_share, 4),
        "top_10pct_cluster_share": round(top_10pct_share, 4),
        "top_clusters": top_clusters,
    }


def build_comparison(cache_enabled: RunSummary, cache_disabled: RunSummary) -> dict[str, float]:
    return {
        "wall_avg_speedup": round(cache_disabled.wall_avg_ms / cache_enabled.wall_avg_ms, 4),
        "app_avg_speedup": round(cache_disabled.app_avg_ms / cache_enabled.app_avg_ms, 4),
        "cost_total_reduction_pct": round(
            100.0 * (1.0 - (cache_enabled.cost_total_usd / cache_disabled.cost_total_usd)),
            4,
        )
        if cache_disabled.cost_total_usd
        else 0.0,
        "cache_enabled_fast_path_rate": round(
            (
                cache_enabled.route_class_counts.get("cache_hit", 0)
                + cache_enabled.route_class_counts.get("validation_success", 0)
            )
            / cache_enabled.requests,
            4,
        ),
        "cache_disabled_fast_path_rate": round(
            (
                cache_disabled.route_class_counts.get("cache_hit", 0)
                + cache_disabled.route_class_counts.get("validation_success", 0)
            )
            / cache_disabled.requests,
            4,
        ),
    }


def maybe_write_json(
    path: str | None,
    catalog: list[TracePrompt],
    workload: list[WorkloadEvent],
    locality: dict[str, object],
    summaries: list[RunSummary],
    comparison: dict[str, float],
    metadata: dict[str, object],
) -> None:
    if not path:
        return
    target = Path(path)
    payload = {
        "metadata": metadata,
        "trace_catalog_summary": {
            "clusters": len({trace.cluster_id for trace in catalog}),
            "unique_prompts": len(catalog),
        },
        "workload_locality": locality,
        "trace_catalog": [asdict(trace) for trace in catalog],
        "workload": [asdict(event) for event in workload],
        "runs": [asdict(summary) for summary in summaries],
        "comparison": comparison,
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_write_csv(path: str | None, samples: list[RequestSample]) -> None:
    if not path:
        return
    target = Path(path)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "run_mode",
                "sequence",
                "cluster_id",
                "prompt_id",
                "cluster_rank",
                "cluster_occurrence",
                "first_seen_cluster",
                "prompt",
                "department",
                "resource_type",
                "wall_ms",
                "app_ms",
                "decision",
                "final_source",
                "route_class",
                "entered_validation_band",
                "reason_code",
                "confidence",
                "cache_similarity",
                "cross_encoder_score",
                "estimated_cost_usd",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            ],
        )
        writer.writeheader()
        for sample in samples:
            row = asdict(sample)
            row["wall_ms"] = round(row["wall_ms"], 2)
            row["confidence"] = round(row["confidence"], 4)
            row["cache_similarity"] = None if row["cache_similarity"] is None else round(row["cache_similarity"], 4)
            row["cross_encoder_score"] = (
                None if row["cross_encoder_score"] is None else round(row["cross_encoder_score"], 4)
            )
            row["estimated_cost_usd"] = round(row["estimated_cost_usd"], 6)
            writer.writerow(row)


def print_run_summary(summary: RunSummary) -> None:
    print(f"\n{summary.run_mode}")
    print(f"  requests={summary.requests}")
    print(f"  final_source_counts={summary.final_source_counts}")
    print(f"  route_class_counts={summary.route_class_counts}")
    print(f"  first_seen_route_class_counts={summary.first_seen_route_class_counts}")
    print(f"  repeat_route_class_counts={summary.repeat_route_class_counts}")
    print(
        "  wall_ms:"
        f" avg={summary.wall_avg_ms:.2f}"
        f" p50={summary.wall_p50_ms:.2f}"
        f" p95={summary.wall_p95_ms:.2f}"
    )
    print(
        "  app_latency_ms:"
        f" avg={summary.app_avg_ms:.2f}"
        f" p50={summary.app_p50_ms:.2f}"
        f" p95={summary.app_p95_ms:.2f}"
    )
    print(
        "  cost_usd:"
        f" total={summary.cost_total_usd:.6f}"
        f" avg={summary.cost_avg_usd:.6f}"
    )
    print(
        "  scores:"
        f" cache_avg={summary.avg_cache_similarity:.4f}"
        f" cross_avg={summary.avg_cross_encoder_score:.4f}"
    )


def main() -> None:
    global CURRENT_REQUEST_RETRIES, CURRENT_REQUEST_TIMEOUT_SECONDS

    parser = argparse.ArgumentParser(description="Macro benchmark with Zipfian semantic locality.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--clusters", type=int, default=40)
    parser.add_argument("--variants-per-cluster", type=int, default=5)
    parser.add_argument("--workload-size", type=int, default=1000)
    parser.add_argument("--zipf-exponent", type=float, default=1.2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--request-retries", type=int, default=DEFAULT_REQUEST_RETRIES)
    parser.add_argument("--json-out", default="macro_benchmark_results.json")
    parser.add_argument("--csv-out", default="macro_benchmark_results.csv")
    args = parser.parse_args()

    CURRENT_REQUEST_TIMEOUT_SECONDS = args.request_timeout_seconds
    CURRENT_REQUEST_RETRIES = args.request_retries

    catalog = build_trace_catalog(clusters=args.clusters, variants_per_cluster=args.variants_per_cluster)
    if not (100 <= len(catalog) <= 500):
        raise RuntimeError(f"trace catalog size must stay within 100-500 prompts; found {len(catalog)}")

    workload = generate_zipfian_workload(
        catalog=catalog,
        workload_size=args.workload_size,
        zipf_exponent=args.zipf_exponent,
        seed=args.seed,
    )
    locality = build_workload_locality(workload)
    run_id = str(uuid4())

    ensure_ready(args.base_url)
    cache_enabled_samples = run_workload(args.base_url, workload, "cache_enabled", run_id)
    cache_disabled_samples = run_workload(args.base_url, workload, "cache_disabled", run_id)

    cache_enabled_summary = build_run_summary("cache_enabled", cache_enabled_samples)
    cache_disabled_summary = build_run_summary("cache_disabled", cache_disabled_samples)
    summaries = [cache_enabled_summary, cache_disabled_summary]
    comparison = build_comparison(cache_enabled_summary, cache_disabled_summary)
    for summary in summaries:
        print_run_summary(summary)
    print(f"\ncomparison\n  {json.dumps(comparison, indent=2)}")

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "clusters": args.clusters,
        "variants_per_cluster": args.variants_per_cluster,
        "workload_size": args.workload_size,
        "zipf_exponent": args.zipf_exponent,
        "seed": args.seed,
        "request_timeout_seconds": args.request_timeout_seconds,
        "request_retries": args.request_retries,
        "run_id": run_id,
    }
    maybe_write_json(args.json_out or None, catalog, workload, locality, summaries, comparison, metadata)
    maybe_write_csv(args.csv_out or None, cache_enabled_samples + cache_disabled_samples)


if __name__ == "__main__":
    main()
