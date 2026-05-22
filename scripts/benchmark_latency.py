from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from app.clients.vector_client import cosine_similarity
from app.dependencies import get_embedding_service, get_mode_manager, get_validation_service
from app.mode_manager import MODE_THRESHOLDS
from app.models import Mode


DEFAULT_VALIDATION_CANDIDATES = [
    "Need access to quarterly report for finance",
    "Request access to the quarterly finance report",
    "Access quarterly finance report",
    "Need the finance quarterly report",
    "Need access to finance report for the quarter",
    "Need access to the quarterly report",
    "Need finance report access",
    "Request finance report access for the quarter",
    "Need access to the quarter finance report",
    "Need the quarterly financial report",
    "Need access to financial report for the quarter",
    "Need access to report for quarterly finance",
    "Need access to finance reporting for the quarter",
    "quarterly finance report access",
    "finance report",
]

DEFAULT_VALIDATION_FALLBACK_CANDIDATES = [
    "Need the policy for quarterly finance report access",
    "Need the template for quarterly finance report access",
    "Need approval workflow for quarterly finance report access",
    "Need training on quarterly finance report access",
    "Need guidelines for quarterly finance reporting access",
    "Need help requesting quarterly finance report access",
    "Need audit steps for quarterly finance report access",
    "Need access log for quarterly finance report",
    "Need summary of quarterly finance report access policy",
    "Need compliance checklist for quarterly finance report access",
]

BENCHMARK_METADATA = {
    "role": "analyst",
    "department": "latency-bench",
    "region": "bench",
    "clearance_level": 2,
    "resource_type": "benchmark_doc",
}

DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
DEFAULT_REQUEST_RETRIES = 1
CURRENT_REQUEST_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT_SECONDS
CURRENT_REQUEST_RETRIES = DEFAULT_REQUEST_RETRIES


@dataclass
class Sample:
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
class Summary:
    name: str
    samples: int
    final_source_counts: dict[str, int]
    route_class_counts: dict[str, int]
    entered_validation_band_count: int
    wall_avg_ms: float
    wall_p50_ms: float
    wall_p95_ms: float
    wall_min_ms: float
    wall_max_ms: float
    app_avg_ms: float
    app_p50_ms: float
    app_p95_ms: float
    app_min_ms: float
    app_max_ms: float
    cost_avg_usd: float
    cost_p50_usd: float
    cost_p95_usd: float
    cost_total_usd: float
    prompt_tokens_total: int
    completion_tokens_total: int
    total_tokens_total: int
    avg_cache_similarity: float
    avg_cross_encoder_score: float


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def build_payload(prompt: str, request_id: str | None = None, metadata_suffix: str = "default") -> dict:
    department = f"{BENCHMARK_METADATA['department']}-{metadata_suffix}"
    resource_id = f"doc-latency-bench-{metadata_suffix}"
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "user": {
            "user_id": "u-latency-bench",
            "role": BENCHMARK_METADATA["role"],
            "department": department,
            "region": BENCHMARK_METADATA["region"],
            "clearance_level": BENCHMARK_METADATA["clearance_level"],
        },
        "context": {
            "ip_address": "10.99.0.10",
            "device_id": "dev-bench",
            "session_id": "sess-bench",
            "mfa_state": "passed",
            "incident_state": "normal",
        },
        "resource": {
            "resource_type": BENCHMARK_METADATA["resource_type"],
            "resource_id": resource_id,
            "sensitivity": "internal",
        },
        "query": {
            "prompt": prompt,
            "purpose": "latency benchmark",
        },
    }


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


def namespaced_suffix(args: argparse.Namespace, label: str) -> str:
    return f"{args.run_id}-{label}"


def build_local_validation_candidates(prompt: str) -> list[str]:
    words = prompt.split()
    candidates = list(DEFAULT_VALIDATION_CANDIDATES)
    if len(words) >= 4:
        candidates.extend(
            [
                " ".join(words[:-1]),
                " ".join(words[1:]),
                " ".join(words[:-2]),
                " ".join(words[:2] + words[3:]),
                " ".join(words[:1] + words[2:]),
                " ".join(reversed(words)),
            ]
        )
    if len(words) >= 3:
        candidates.extend(
            [
                f"{words[0]} {words[-2]} {words[-1]}",
                f"{words[0]} {' '.join(words[2:])}",
                f"{' '.join(words[:-1])} access",
            ]
        )
    # Preserve order while removing duplicates/empties.
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        candidate = " ".join(candidate.split()).strip()
        if not candidate or candidate == prompt or candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def build_local_validation_fallback_candidates(prompt: str) -> list[str]:
    words = prompt.split()
    candidates = list(DEFAULT_VALIDATION_FALLBACK_CANDIDATES)
    if len(words) >= 4:
        candidates.extend(
            [
                f"Need the policy for {' '.join(words[2:])}",
                f"Need the template for {' '.join(words[2:])}",
                f"Need approval workflow for {' '.join(words[2:])}",
                f"Need training on {' '.join(words[2:])}",
                f"Need help requesting {' '.join(words[2:])}",
                f"Need the access log for {' '.join(words[2:])}",
            ]
        )
    if len(words) >= 3:
        tail = " ".join(words[-3:])
        candidates.extend(
            [
                f"Need the policy for {tail}",
                f"Need the template for {tail}",
                f"Need approval workflow for {tail}",
                f"Need help requesting {tail}",
            ]
        )
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        candidate = " ".join(candidate.split()).strip()
        if not candidate or candidate == prompt or candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def post_decision(base_url: str, payload: dict) -> Sample:
    timeout_seconds = float(payload.pop("_request_timeout_seconds", CURRENT_REQUEST_TIMEOUT_SECONDS))
    request_retries = int(payload.pop("_request_retries", CURRENT_REQUEST_RETRIES))
    last_exc: Exception | None = None
    for attempt in range(request_retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                start = time.perf_counter()
                response = client.post(f"{base_url}/v1/access/decide", json=payload)
                wall_ms = (time.perf_counter() - start) * 1000
                response.raise_for_status()
                body = response.json()
            break
        except httpx.ReadTimeout as exc:
            last_exc = exc
            if attempt >= request_retries:
                raise
            log(
                f"request timeout attempt={attempt + 1}/{request_retries + 1} "
                f"timeout_seconds={timeout_seconds} request_id={payload.get('request_id')}"
            )
    else:
        raise last_exc or RuntimeError("request failed without exception details")
    scores = body.get("scores") or {}
    final_source = body["decision_source"]
    entered_validation_band, route_class = classify_route(
        final_source=final_source,
        cache_similarity=scores.get("cache_similarity"),
        mode=body["mode"],
    )
    return Sample(
        wall_ms=wall_ms,
        app_ms=int(body["latency_ms"]),
        decision=body["decision"],
        final_source=final_source,
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


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def build_summary(name: str, samples: list[Sample]) -> Summary:
    wall = [s.wall_ms for s in samples]
    app = [float(s.app_ms) for s in samples]
    cost = [s.estimated_cost_usd for s in samples]
    cache_scores = [float(s.cache_similarity) for s in samples if s.cache_similarity is not None]
    cross_scores = [float(s.cross_encoder_score) for s in samples if s.cross_encoder_score is not None]
    final_source_counts = dict(Counter(s.final_source for s in samples))
    route_class_counts = dict(Counter(s.route_class for s in samples))
    return Summary(
        name=name,
        samples=len(samples),
        final_source_counts=final_source_counts,
        route_class_counts=route_class_counts,
        entered_validation_band_count=sum(1 for s in samples if s.entered_validation_band),
        wall_avg_ms=statistics.mean(wall),
        wall_p50_ms=percentile(wall, 50),
        wall_p95_ms=percentile(wall, 95),
        wall_min_ms=min(wall),
        wall_max_ms=max(wall),
        app_avg_ms=statistics.mean(app),
        app_p50_ms=percentile(app, 50),
        app_p95_ms=percentile(app, 95),
        app_min_ms=min(app),
        app_max_ms=max(app),
        cost_avg_usd=statistics.mean(cost),
        cost_p50_usd=percentile(cost, 50),
        cost_p95_usd=percentile(cost, 95),
        cost_total_usd=sum(cost),
        prompt_tokens_total=sum(s.prompt_tokens for s in samples),
        completion_tokens_total=sum(s.completion_tokens for s in samples),
        total_tokens_total=sum(s.total_tokens for s in samples),
        avg_cache_similarity=statistics.mean(cache_scores) if cache_scores else 0.0,
        avg_cross_encoder_score=statistics.mean(cross_scores) if cross_scores else 0.0,
    )


def print_summary(summary: Summary) -> None:
    print(f"\n{summary.name}")
    print(f"  samples={summary.samples}")
    print(f"  final_source_counts={summary.final_source_counts}")
    print(f"  route_class_counts={summary.route_class_counts}")
    print(f"  entered_validation_band={summary.entered_validation_band_count}")
    print(
        "  wall_ms:"
        f" avg={summary.wall_avg_ms:.2f}"
        f" p50={summary.wall_p50_ms:.2f}"
        f" p95={summary.wall_p95_ms:.2f}"
        f" min={summary.wall_min_ms:.2f}"
        f" max={summary.wall_max_ms:.2f}"
    )
    print(
        "  app_latency_ms:"
        f" avg={summary.app_avg_ms:.2f}"
        f" p50={summary.app_p50_ms:.2f}"
        f" p95={summary.app_p95_ms:.2f}"
        f" min={summary.app_min_ms:.2f}"
        f" max={summary.app_max_ms:.2f}"
    )
    print(
        "  cost_usd:"
        f" total={summary.cost_total_usd:.6f}"
        f" avg={summary.cost_avg_usd:.6f}"
        f" p50={summary.cost_p50_usd:.6f}"
        f" p95={summary.cost_p95_usd:.6f}"
    )
    print(
        "  scores:"
        f" cache_avg={summary.avg_cache_similarity:.4f}"
        f" cross_avg={summary.avg_cross_encoder_score:.4f}"
    )
    print(
        "  tokens:"
        f" prompt_total={summary.prompt_tokens_total}"
        f" completion_total={summary.completion_tokens_total}"
        f" total={summary.total_tokens_total}"
    )


def ensure_ready(base_url: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        health = client.get(f"{base_url}/health")
        health.raise_for_status()
        ready = client.get(f"{base_url}/ready")
        ready.raise_for_status()
        body = ready.json()
    if body.get("status") != "ready":
        raise RuntimeError(f"service not ready: {json.dumps(body, indent=2)}")


def warm_up(base_url: str) -> None:
    log("warmup start")
    payload = build_payload(
        prompt="Warm up semantic ACL benchmark path",
        request_id=f"warmup-{uuid4()}",
        metadata_suffix=f"warmup-{uuid4()}",
    )
    post_decision(base_url, payload)
    log("warmup complete")


def assert_expected_sources(name: str, samples: list[Sample], expected_source: str) -> None:
    mismatches = [sample for sample in samples if sample.final_source != expected_source]
    if not mismatches:
        return
    details = [
        {
            "final_source": sample.final_source,
            "route_class": sample.route_class,
            "entered_validation_band": sample.entered_validation_band,
            "decision": sample.decision,
            "reason_code": sample.reason_code,
            "cache_similarity": sample.cache_similarity,
            "cross_encoder_score": sample.cross_encoder_score,
        }
        for sample in mismatches[:5]
    ]
    raise RuntimeError(
        f"{name} expected source '{expected_source}' but found mismatches: {json.dumps(details, indent=2)}"
    )


def assert_expected_route_class(name: str, samples: list[Sample], expected_route_class: str) -> None:
    mismatches = [sample for sample in samples if sample.route_class != expected_route_class]
    if not mismatches:
        return
    details = [
        {
            "final_source": sample.final_source,
            "route_class": sample.route_class,
            "entered_validation_band": sample.entered_validation_band,
            "decision": sample.decision,
            "reason_code": sample.reason_code,
            "cache_similarity": sample.cache_similarity,
            "cross_encoder_score": sample.cross_encoder_score,
        }
        for sample in mismatches[:5]
    ]
    raise RuntimeError(
        f"{name} expected route_class '{expected_route_class}' but found mismatches: {json.dumps(details, indent=2)}"
    )


def prime_cache_for_prompt(base_url: str, prompt: str, metadata_suffix: str) -> Sample:
    seed_payload = build_payload(
        prompt=prompt,
        request_id=f"seed-{uuid4()}",
        metadata_suffix=metadata_suffix,
    )
    return post_decision(base_url, seed_payload)


def confirm_cache_hit(base_url: str, prompt: str, metadata_suffix: str, retries: int) -> None:
    log(f"confirm cache-hit start metadata_suffix={metadata_suffix}")
    for attempt in range(retries):
        payload = build_payload(
            prompt=prompt,
            request_id=f"confirm-hit-{attempt}-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(base_url, payload)
        log(
            f"confirm cache-hit attempt={attempt + 1}/{retries} "
            f"final_source={sample.final_source} cache_similarity={sample.cache_similarity}"
        )
        if sample.final_source == "cache":
            log("confirm cache-hit complete")
            return
    raise RuntimeError(
        f"cache hit confirmation failed for metadata_suffix={metadata_suffix}; "
        "cache path did not activate after seeding"
    )


def confirm_validation_prompt(
    base_url: str,
    seed_prompt: str,
    validation_prompt: str,
    retries: int,
) -> None:
    log(f"confirm validation start prompt={validation_prompt!r}")
    for attempt in range(retries):
        metadata_suffix = f"validation-confirm-{attempt}-{uuid4()}"
        prime_cache_for_prompt(base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=validation_prompt,
            request_id=f"validation-confirm-{attempt}-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(base_url, payload)
        log(
            f"confirm validation attempt={attempt + 1}/{retries} "
            f"final_source={sample.final_source} cache_similarity={sample.cache_similarity} "
            f"cross_encoder_score={sample.cross_encoder_score}"
        )
        if sample.final_source == "validation":
            log("confirm validation complete")
            return
    raise RuntimeError(
        f"validation prompt confirmation failed for prompt={validation_prompt!r}; "
        "validation path did not activate during confirmation"
    )


def confirm_validation_fallback_prompt(
    base_url: str,
    seed_prompt: str,
    fallback_prompt: str,
    retries: int,
) -> None:
    log(f"confirm validation fallback start prompt={fallback_prompt!r}")
    for attempt in range(retries):
        metadata_suffix = f"validation-fallback-confirm-{attempt}-{uuid4()}"
        prime_cache_for_prompt(base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=fallback_prompt,
            request_id=f"validation-fallback-confirm-{attempt}-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(base_url, payload)
        log(
            f"confirm validation fallback attempt={attempt + 1}/{retries} "
            f"final_source={sample.final_source} route_class={sample.route_class} "
            f"cache_similarity={sample.cache_similarity} cross_encoder_score={sample.cross_encoder_score}"
        )
        if sample.route_class == "validation_fallback_llm":
            log("confirm validation fallback complete")
            return
    raise RuntimeError(
        f"validation fallback prompt confirmation failed for prompt={fallback_prompt!r}; "
        "validation-fallback path did not activate during confirmation"
    )


def calibrate_validation_prompt(
    base_url: str,
    seed_prompt: str,
    candidates: list[str],
    max_candidates: int,
) -> str:
    thresholds = get_mode_manager().thresholds()
    target_mid = (thresholds.t_validate_low + thresholds.t_hit) / 2.0
    embedding = get_embedding_service()
    seed_vector = embedding.encode(seed_prompt)
    ranked_candidates: list[tuple[float, str, float]] = []
    local_observations: list[dict[str, object]] = []
    all_candidates = build_local_validation_candidates(seed_prompt) + candidates
    limited_candidates = all_candidates[:max_candidates]
    log(
        "calibrate validation start "
        f"candidates={len(limited_candidates)} band=[{thresholds.t_validate_low:.2f}, {thresholds.t_hit:.2f})"
    )
    for idx, candidate in enumerate(limited_candidates, start=1):
        candidate_vector = embedding.encode(candidate)
        similarity = cosine_similarity(seed_vector, candidate_vector)
        local_observations.append({"candidate": candidate, "local_similarity": similarity})
        log(
            f"local calibration candidate={idx}/{len(limited_candidates)} "
            f"similarity={similarity:.4f} prompt={candidate!r}"
        )
        if thresholds.t_validate_low <= similarity < thresholds.t_hit:
            ranked_candidates.append((abs(similarity - target_mid), candidate, similarity))

    if not ranked_candidates:
        compact = [
            {
                "candidate": item["candidate"],
                "local_similarity": round(float(item["local_similarity"]), 4),
            }
            for item in local_observations[:20]
        ]
        raise RuntimeError(
            "failed to find a local validation-band prompt; local observations="
            + json.dumps(compact, indent=2)
        )

    ranked_candidates.sort(key=lambda item: item[0])
    log(
        "local calibration selected candidates="
        + json.dumps(
            [
                {"prompt": candidate, "local_similarity": round(similarity, 4)}
                for _, candidate, similarity in ranked_candidates[:3]
            ],
            indent=2,
        )
    )

    observations: list[dict[str, object]] = []
    for idx, (_, candidate, local_similarity) in enumerate(ranked_candidates[: min(3, len(ranked_candidates))], start=1):
        metadata_suffix = f"validation-calibration-{uuid4()}"
        prime_cache_for_prompt(base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=candidate,
            request_id=f"validation-calibration-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(base_url, payload)
        log(
            f"api calibration candidate={idx}/{min(3, len(ranked_candidates))} "
            f"final_source={sample.final_source} cache_similarity={sample.cache_similarity} "
            f"cross_encoder_score={sample.cross_encoder_score} prompt={candidate!r}"
        )
        observations.append(
            {
                "candidate": candidate,
                "local_similarity": local_similarity,
                "final_source": sample.final_source,
                "route_class": sample.route_class,
                "entered_validation_band": sample.entered_validation_band,
                "reason_code": sample.reason_code,
                "cache_similarity": sample.cache_similarity,
                "cross_encoder_score": sample.cross_encoder_score,
            }
        )
        if sample.final_source == "validation":
            log(f"calibrate validation complete selected={candidate!r}")
            return candidate

    compact = [
        {
            "candidate": item["candidate"],
            "local_similarity": round(float(item["local_similarity"]), 4),
            "final_source": item["final_source"],
            "route_class": item["route_class"],
            "entered_validation_band": item["entered_validation_band"],
            "reason_code": item["reason_code"],
            "cache_similarity": item["cache_similarity"],
            "cross_encoder_score": item["cross_encoder_score"],
        }
        for item in observations[:20]
    ]
    raise RuntimeError(
        "failed to calibrate a validation-band prompt; observations="
        + json.dumps(compact, indent=2)
    )


def calibrate_validation_fallback_prompt(
    base_url: str,
    seed_prompt: str,
    candidates: list[str],
    max_candidates: int,
) -> str:
    thresholds = get_mode_manager().thresholds()
    target_mid = (thresholds.t_validate_low + thresholds.t_hit) / 2.0
    embedding = get_embedding_service()
    validator = get_validation_service()
    seed_vector = embedding.encode(seed_prompt)
    ranked_candidates: list[tuple[float, str, float, float]] = []
    local_observations: list[dict[str, object]] = []
    all_candidates = build_local_validation_fallback_candidates(seed_prompt) + candidates
    limited_candidates = all_candidates[:max_candidates]
    log(
        "calibrate validation fallback start "
        f"candidates={len(limited_candidates)} band=[{thresholds.t_validate_low:.2f}, {thresholds.t_hit:.2f}) "
        f"validation_threshold={validator.threshold:.2f}"
    )
    for idx, candidate in enumerate(limited_candidates, start=1):
        candidate_vector = embedding.encode(candidate)
        similarity = cosine_similarity(seed_vector, candidate_vector)
        validation = validator.validate(candidate, seed_prompt)
        local_observations.append(
            {
                "candidate": candidate,
                "local_similarity": similarity,
                "local_cross_encoder_score": validation.score,
            }
        )
        log(
            f"local fallback candidate={idx}/{len(limited_candidates)} "
            f"similarity={similarity:.4f} cross_encoder_score={validation.score:.4f} prompt={candidate!r}"
        )
        if thresholds.t_validate_low <= similarity < thresholds.t_hit and validation.score < validator.threshold:
            ranked_candidates.append((abs(similarity - target_mid), candidate, similarity, validation.score))

    if not ranked_candidates:
        compact = [
            {
                "candidate": item["candidate"],
                "local_similarity": round(float(item["local_similarity"]), 4),
                "local_cross_encoder_score": round(float(item["local_cross_encoder_score"]), 4),
            }
            for item in local_observations[:20]
        ]
        raise RuntimeError(
            "failed to find a local validation-fallback prompt; local observations="
            + json.dumps(compact, indent=2)
        )

    ranked_candidates.sort(key=lambda item: (item[0], item[3]))
    log(
        "local fallback selected candidates="
        + json.dumps(
            [
                {
                    "prompt": candidate,
                    "local_similarity": round(similarity, 4),
                    "local_cross_encoder_score": round(score, 4),
                }
                for _, candidate, similarity, score in ranked_candidates[:3]
            ],
            indent=2,
        )
    )

    observations: list[dict[str, object]] = []
    for idx, (_, candidate, local_similarity, local_score) in enumerate(
        ranked_candidates[: min(3, len(ranked_candidates))], start=1
    ):
        metadata_suffix = f"validation-fallback-calibration-{uuid4()}"
        prime_cache_for_prompt(base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=candidate,
            request_id=f"validation-fallback-calibration-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(base_url, payload)
        log(
            f"api fallback candidate={idx}/{min(3, len(ranked_candidates))} "
            f"final_source={sample.final_source} route_class={sample.route_class} "
            f"cache_similarity={sample.cache_similarity} cross_encoder_score={sample.cross_encoder_score} "
            f"prompt={candidate!r}"
        )
        observations.append(
            {
                "candidate": candidate,
                "local_similarity": local_similarity,
                "local_cross_encoder_score": local_score,
                "final_source": sample.final_source,
                "route_class": sample.route_class,
                "entered_validation_band": sample.entered_validation_band,
                "reason_code": sample.reason_code,
                "cache_similarity": sample.cache_similarity,
                "cross_encoder_score": sample.cross_encoder_score,
            }
        )
        if sample.route_class == "validation_fallback_llm":
            log(f"calibrate validation fallback complete selected={candidate!r}")
            return candidate

    compact = [
        {
            "candidate": item["candidate"],
            "local_similarity": round(float(item["local_similarity"]), 4),
            "local_cross_encoder_score": round(float(item["local_cross_encoder_score"]), 4),
            "final_source": item["final_source"],
            "route_class": item["route_class"],
            "entered_validation_band": item["entered_validation_band"],
            "reason_code": item["reason_code"],
            "cache_similarity": item["cache_similarity"],
            "cross_encoder_score": item["cross_encoder_score"],
        }
        for item in observations[:20]
    ]
    raise RuntimeError(
        "failed to calibrate a validation-fallback prompt; observations="
        + json.dumps(compact, indent=2)
    )


def run_cache_miss_benchmark(args: argparse.Namespace) -> list[Sample]:
    samples: list[Sample] = []
    log(f"cache_miss start iterations={args.iterations}")
    for i in range(args.iterations):
        prompt = f"{args.prompt} miss iteration {i} token {uuid4()}"
        payload = build_payload(prompt=prompt, metadata_suffix=namespaced_suffix(args, f"miss-{i}"))
        sample = post_decision(args.base_url, payload)
        samples.append(sample)
        log(
            f"cache_miss progress {i + 1}/{args.iterations} "
            f"final_source={sample.final_source} route_class={sample.route_class} wall_ms={sample.wall_ms:.2f}"
        )
    assert_expected_sources("cache_miss", samples, "llm")
    log("cache_miss complete")
    return samples


def run_cache_hit_benchmark(args: argparse.Namespace) -> list[Sample]:
    samples: list[Sample] = []
    prompt = args.prompt
    metadata_suffix = namespaced_suffix(args, f"hit-{uuid4()}")

    log(f"cache_hit start iterations={args.iterations}")
    prime_cache_for_prompt(args.base_url, prompt, metadata_suffix)
    confirm_cache_hit(args.base_url, prompt, metadata_suffix, args.confirm_retries)

    for i in range(args.iterations):
        payload = build_payload(prompt=prompt, request_id=f"hit-{i}-{uuid4()}", metadata_suffix=metadata_suffix)
        sample = post_decision(args.base_url, payload)
        samples.append(sample)
        log(
            f"cache_hit progress {i + 1}/{args.iterations} "
            f"final_source={sample.final_source} route_class={sample.route_class} wall_ms={sample.wall_ms:.2f}"
        )
    assert_expected_sources("cache_hit", samples, "cache")
    log("cache_hit complete")
    return samples


def run_validation_benchmark(args: argparse.Namespace) -> tuple[list[Sample], str]:
    samples: list[Sample] = []
    seed_prompt = args.prompt
    log(f"validation_band start iterations={args.iterations}")
    validation_prompt = args.validation_prompt or calibrate_validation_prompt(
        args.base_url,
        seed_prompt=seed_prompt,
        candidates=args.validation_candidates,
        max_candidates=args.validation_max_candidates,
    )
    confirm_validation_prompt(args.base_url, seed_prompt, validation_prompt, args.confirm_retries)

    for i in range(args.iterations):
        metadata_suffix = namespaced_suffix(args, f"validation-{i}-{uuid4()}")
        prime_cache_for_prompt(args.base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=validation_prompt,
            request_id=f"validation-{i}-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(args.base_url, payload)
        samples.append(sample)
        log(
            f"validation_band progress {i + 1}/{args.iterations} "
            f"final_source={sample.final_source} route_class={sample.route_class} wall_ms={sample.wall_ms:.2f}"
        )
    assert_expected_sources("validation_band", samples, "validation")
    log("validation_band complete")
    return samples, validation_prompt


def run_validation_fallback_benchmark(args: argparse.Namespace) -> tuple[list[Sample], str]:
    samples: list[Sample] = []
    seed_prompt = args.prompt
    log(f"validation_fallback_llm start iterations={args.iterations}")
    fallback_prompt = args.validation_fallback_prompt or calibrate_validation_fallback_prompt(
        args.base_url,
        seed_prompt=seed_prompt,
        candidates=args.validation_fallback_candidates,
        max_candidates=args.validation_fallback_max_candidates,
    )
    confirm_validation_fallback_prompt(args.base_url, seed_prompt, fallback_prompt, args.confirm_retries)

    for i in range(args.iterations):
        metadata_suffix = namespaced_suffix(args, f"validation-fallback-{i}-{uuid4()}")
        prime_cache_for_prompt(args.base_url, seed_prompt, metadata_suffix)
        payload = build_payload(
            prompt=fallback_prompt,
            request_id=f"validation-fallback-{i}-{uuid4()}",
            metadata_suffix=metadata_suffix,
        )
        sample = post_decision(args.base_url, payload)
        samples.append(sample)
        log(
            f"validation_fallback_llm progress {i + 1}/{args.iterations} "
            f"final_source={sample.final_source} route_class={sample.route_class} wall_ms={sample.wall_ms:.2f}"
        )
    assert_expected_route_class("validation_fallback_llm", samples, "validation_fallback_llm")
    log("validation_fallback_llm complete")
    return samples, fallback_prompt


def maybe_write_json(path: str | None, summaries: list[Summary], metadata: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    payload = {
        "metadata": metadata,
        "summaries": [
            {
                "name": s.name,
                "samples": s.samples,
                "final_source_counts": s.final_source_counts,
                "route_class_counts": s.route_class_counts,
                "entered_validation_band_count": s.entered_validation_band_count,
                "wall_ms": {
                    "avg": s.wall_avg_ms,
                    "p50": s.wall_p50_ms,
                    "p95": s.wall_p95_ms,
                    "min": s.wall_min_ms,
                    "max": s.wall_max_ms,
                },
                "app_latency_ms": {
                    "avg": s.app_avg_ms,
                    "p50": s.app_p50_ms,
                    "p95": s.app_p95_ms,
                    "min": s.app_min_ms,
                    "max": s.app_max_ms,
                },
                "cost_usd": {
                    "total": s.cost_total_usd,
                    "avg": s.cost_avg_usd,
                    "p50": s.cost_p50_usd,
                    "p95": s.cost_p95_usd,
                },
                "scores": {
                    "cache_avg": s.avg_cache_similarity,
                    "cross_avg": s.avg_cross_encoder_score,
                },
                "tokens": {
                    "prompt_total": s.prompt_tokens_total,
                    "completion_total": s.completion_tokens_total,
                    "total": s.total_tokens_total,
                },
            }
            for s in summaries
        ],
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_write_csv(
    path: str | None,
    summaries: list[Summary],
    validation_prompt: str,
    validation_fallback_prompt: str,
) -> None:
    if not path:
        return
    target = Path(path)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "name",
                "samples",
                "final_source_counts",
                "route_class_counts",
                "entered_validation_band_count",
                "validation_prompt_used",
                "validation_fallback_prompt_used",
                "wall_avg_ms",
                "wall_p50_ms",
                "wall_p95_ms",
                "wall_min_ms",
                "wall_max_ms",
                "app_avg_ms",
                "app_p50_ms",
                "app_p95_ms",
                "app_min_ms",
                "app_max_ms",
                "cost_total_usd",
                "cost_avg_usd",
                "cost_p50_usd",
                "cost_p95_usd",
                "avg_cache_similarity",
                "avg_cross_encoder_score",
                "prompt_tokens_total",
                "completion_tokens_total",
                "total_tokens_total",
            ],
        )
        writer.writeheader()
        for s in summaries:
            writer.writerow(
                {
                    "name": s.name,
                    "samples": s.samples,
                    "final_source_counts": json.dumps(s.final_source_counts),
                    "route_class_counts": json.dumps(s.route_class_counts),
                    "entered_validation_band_count": s.entered_validation_band_count,
                    "validation_prompt_used": validation_prompt if s.name == "validation_band" else "",
                    "validation_fallback_prompt_used": (
                        validation_fallback_prompt if s.name == "validation_fallback_llm" else ""
                    ),
                    "wall_avg_ms": round(s.wall_avg_ms, 2),
                    "wall_p50_ms": round(s.wall_p50_ms, 2),
                    "wall_p95_ms": round(s.wall_p95_ms, 2),
                    "wall_min_ms": round(s.wall_min_ms, 2),
                    "wall_max_ms": round(s.wall_max_ms, 2),
                    "app_avg_ms": round(s.app_avg_ms, 2),
                    "app_p50_ms": round(s.app_p50_ms, 2),
                    "app_p95_ms": round(s.app_p95_ms, 2),
                    "app_min_ms": round(s.app_min_ms, 2),
                    "app_max_ms": round(s.app_max_ms, 2),
                    "cost_total_usd": round(s.cost_total_usd, 6),
                    "cost_avg_usd": round(s.cost_avg_usd, 6),
                    "cost_p50_usd": round(s.cost_p50_usd, 6),
                    "cost_p95_usd": round(s.cost_p95_usd, 6),
                    "avg_cache_similarity": round(s.avg_cache_similarity, 4),
                    "avg_cross_encoder_score": round(s.avg_cross_encoder_score, 4),
                    "prompt_tokens_total": s.prompt_tokens_total,
                    "completion_tokens_total": s.completion_tokens_total,
                    "total_tokens_total": s.total_tokens_total,
                }
            )


def main() -> None:
    global CURRENT_REQUEST_RETRIES, CURRENT_REQUEST_TIMEOUT_SECONDS

    parser = argparse.ArgumentParser(description="Benchmark semantic-cache hit, validation, and miss latency.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--prompt", default="Need access to quarterly finance report")
    parser.add_argument("--validation-prompt", default="")
    parser.add_argument("--validation-fallback-prompt", default="")
    parser.add_argument("--confirm-retries", type=int, default=3)
    parser.add_argument("--validation-max-candidates", type=int, default=18)
    parser.add_argument("--validation-fallback-max-candidates", type=int, default=24)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--request-retries", type=int, default=DEFAULT_REQUEST_RETRIES)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--csv-out", default="")
    args = parser.parse_args()
    args.validation_candidates = DEFAULT_VALIDATION_CANDIDATES
    args.validation_fallback_candidates = DEFAULT_VALIDATION_FALLBACK_CANDIDATES
    args.run_id = str(uuid4())
    CURRENT_REQUEST_TIMEOUT_SECONDS = args.request_timeout_seconds
    CURRENT_REQUEST_RETRIES = args.request_retries

    ensure_ready(args.base_url)
    warm_up(args.base_url)
    miss_samples = run_cache_miss_benchmark(args)
    validation_samples, validation_prompt = run_validation_benchmark(args)
    validation_fallback_samples, validation_fallback_prompt = run_validation_fallback_benchmark(args)
    hit_samples = run_cache_hit_benchmark(args)

    summaries = [
        build_summary("cache_miss", miss_samples),
        build_summary("validation_band", validation_samples),
        build_summary("validation_fallback_llm", validation_fallback_samples),
        build_summary("cache_hit", hit_samples),
    ]
    for summary in summaries:
        print_summary(summary)
    metadata = {
        "base_url": args.base_url,
        "iterations": args.iterations,
        "prompt": args.prompt,
        "validation_prompt_used": validation_prompt,
        "validation_fallback_prompt_used": validation_fallback_prompt,
        "confirm_retries": args.confirm_retries,
        "request_timeout_seconds": args.request_timeout_seconds,
        "request_retries": args.request_retries,
        "run_id": args.run_id,
    }
    maybe_write_json(args.json_out or None, summaries, metadata)
    maybe_write_csv(args.csv_out or None, summaries, validation_prompt, validation_fallback_prompt)


if __name__ == "__main__":
    main()
