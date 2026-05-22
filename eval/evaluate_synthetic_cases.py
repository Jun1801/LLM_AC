from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

import httpx

from app.clients.ticket_client import TicketStoreClient
from app.config import get_settings
from app.rationale import build_grounding_facts, grounded_facts_only


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = REPO_ROOT / "eval" / "phase_a_synthetic_cases.jsonl"
DEFAULT_JSON_OUT = REPO_ROOT / "eval" / "outputs" / "benchmark" / "phase_a_eval_results.json"
DEFAULT_CSV_OUT = REPO_ROOT / "eval" / "outputs" / "benchmark" / "phase_a_eval_results.csv"

ALLOW_LIKE = {"ALLOW", "ALLOW_CACHE", "ALLOW_EMERGENCY"}


@dataclass
class SyntheticCase:
    case_id: str
    category: str
    expected_policy_stage: str
    expected_decision: str
    expected_reason_code: str
    expected_decision_basis: str
    ticket_present: bool
    request: dict
    expected_hard_policy: dict
    expected_soft_policy: dict | None


@dataclass
class EvaluationResult:
    case_id: str
    category: str
    expected_policy_stage: str
    expected_decision: str
    expected_reason_code: str
    actual_decision: str | None
    actual_reason_code: str | None
    actual_decision_source: str | None
    actual_latency_ms: int | None
    actual_cost_usd: float
    actual_confidence: float | None
    actual_rationale_summary: str | None
    actual_rationale_facts: list[str]
    decision_exact_match: bool
    decision_family_match: bool
    reason_code_match: bool
    rationale_present: bool
    rationale_grounded: bool
    false_allow: bool
    false_deny: bool
    false_escalate: bool
    skipped: bool
    skipped_reason: str
    error: str


def decision_family(decision: str | None) -> str:
    if decision in ALLOW_LIKE:
        return "allow"
    if decision == "DENY":
        return "deny"
    if decision == "ESCALATE_HUMAN":
        return "escalate"
    return "unknown"


def load_cases(dataset_path: Path) -> list[SyntheticCase]:
    cases: list[SyntheticCase] = []
    with dataset_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            cases.append(SyntheticCase(**payload))
    return cases


def namespace_request(request_payload: dict, run_id: str, case_id: str, *, shared: bool) -> dict:
    payload = deepcopy(request_payload)
    suffix = f"{run_id}-{case_id}"
    unique_suffix = suffix if shared else f"{suffix}-{uuid4()}"
    payload["request_id"] = f"{payload['request_id']}-{uuid4()}"
    payload["user"]["user_id"] = f"{payload['user']['user_id']}-{suffix}"
    payload["user"]["department"] = f"{payload['user']['department']}-{suffix}"
    payload["context"]["device_id"] = f"{payload['context']['device_id']}-{unique_suffix}"
    session_id = payload["context"].get("session_id", "")
    if session_id:
        payload["context"]["session_id"] = f"{session_id}-{unique_suffix}"
    payload["resource"]["resource_id"] = f"{payload['resource']['resource_id']}-{suffix}"
    return payload


def post_decision(base_url: str, payload: dict, timeout_seconds: float) -> dict:
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(f"{base_url}/v1/access/decide", json=payload)
        response.raise_for_status()
        return response.json()


def issue_ticket_if_possible(ticket_store: TicketStoreClient | None, request_payload: dict) -> tuple[bool, str]:
    if ticket_store is None:
        return False, "ticket_store_unavailable"
    ticket_store.issue_ticket(
        request_payload["user"]["user_id"],
        request_payload["resource"]["resource_id"],
        ttl_seconds=900,
    )
    if not ticket_store.has_ticket(request_payload["user"]["user_id"], request_payload["resource"]["resource_id"]):
        return False, "ticket_issue_failed"
    return True, ""


def score_response(case: SyntheticCase, body: dict | None, *, skipped: bool, skipped_reason: str = "", error: str = "") -> EvaluationResult:
    actual_decision = body.get("decision") if body else None
    actual_reason_code = body.get("reason_code") if body else None
    rationale = (body or {}).get("rationale") or {}
    rationale_summary = rationale.get("summary")
    rationale_facts = rationale.get("facts") or []
    allowed_facts = build_grounding_facts(case.request)
    grounded_facts = grounded_facts_only(rationale_facts, allowed_facts)
    expected_family = decision_family(case.expected_decision)
    actual_family = decision_family(actual_decision)
    return EvaluationResult(
        case_id=case.case_id,
        category=case.category,
        expected_policy_stage=case.expected_policy_stage,
        expected_decision=case.expected_decision,
        expected_reason_code=case.expected_reason_code,
        actual_decision=actual_decision,
        actual_reason_code=actual_reason_code,
        actual_decision_source=body.get("decision_source") if body else None,
        actual_latency_ms=body.get("latency_ms") if body else None,
        actual_cost_usd=float(body.get("estimated_cost_usd", 0.0) or 0.0) if body else 0.0,
        actual_confidence=float(body.get("confidence", 0.0) or 0.0) if body else None,
        actual_rationale_summary=str(rationale_summary).strip() or None if rationale_summary is not None else None,
        actual_rationale_facts=grounded_facts if body else [],
        decision_exact_match=bool(body) and actual_decision == case.expected_decision,
        decision_family_match=bool(body) and actual_family == expected_family,
        reason_code_match=bool(body) and actual_reason_code == case.expected_reason_code,
        rationale_present=bool(body) and bool((str(rationale_summary).strip() if rationale_summary is not None else "") or grounded_facts),
        rationale_grounded=bool(body)
        and bool((str(rationale_summary).strip() if rationale_summary is not None else "") or rationale_facts)
        and len(grounded_facts) == len([fact for fact in rationale_facts if isinstance(fact, str)]),
        false_allow=bool(body) and expected_family != "allow" and actual_family == "allow",
        false_deny=bool(body) and expected_family == "allow" and actual_family in {"deny", "escalate"},
        false_escalate=bool(body) and expected_family != "escalate" and actual_family == "escalate",
        skipped=skipped,
        skipped_reason=skipped_reason,
        error=error,
    )


def summarize(results: list[EvaluationResult]) -> dict:
    evaluated = [result for result in results if not result.skipped and not result.error]
    skipped = [result for result in results if result.skipped]
    failed = [result for result in results if result.error]

    def ratio(flag_getter: Callable[[EvaluationResult], bool]) -> float:
        if not evaluated:
            return 0.0
        return sum(1 for result in evaluated if flag_getter(result)) / len(evaluated)

    by_category: dict[str, dict] = {}
    for category in sorted({result.category for result in results}):
        subset = [result for result in evaluated if result.category == category]
        if not subset:
            continue
        by_category[category] = {
            "count": len(subset),
            "decision_exact_accuracy": ratio_on(subset, lambda item: item.decision_exact_match),
            "decision_family_accuracy": ratio_on(subset, lambda item: item.decision_family_match),
            "reason_code_accuracy": ratio_on(subset, lambda item: item.reason_code_match),
            "rationale_presence_rate": ratio_on(subset, lambda item: item.rationale_present),
            "rationale_grounded_rate": ratio_on(subset, lambda item: item.rationale_grounded),
            "false_allow_rate": ratio_on(subset, lambda item: item.false_allow),
            "false_deny_rate": ratio_on(subset, lambda item: item.false_deny),
            "false_escalate_rate": ratio_on(subset, lambda item: item.false_escalate),
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "evaluated_cases": len(evaluated),
        "skipped_cases": len(skipped),
        "error_cases": len(failed),
        "decision_exact_accuracy": ratio(lambda item: item.decision_exact_match),
        "decision_family_accuracy": ratio(lambda item: item.decision_family_match),
        "reason_code_accuracy": ratio(lambda item: item.reason_code_match),
        "rationale_presence_rate": ratio(lambda item: item.rationale_present),
        "rationale_grounded_rate": ratio(lambda item: item.rationale_grounded),
        "false_allow_rate": ratio(lambda item: item.false_allow),
        "false_deny_rate": ratio(lambda item: item.false_deny),
        "false_escalate_rate": ratio(lambda item: item.false_escalate),
        "actual_decision_counts": dict(Counter(result.actual_decision for result in evaluated if result.actual_decision)),
        "actual_reason_code_counts": dict(Counter(result.actual_reason_code for result in evaluated if result.actual_reason_code)),
        "actual_source_counts": dict(
            Counter(result.actual_decision_source for result in evaluated if result.actual_decision_source)
        ),
        "skipped_reason_counts": dict(Counter(result.skipped_reason for result in skipped if result.skipped_reason)),
        "error_counts": dict(Counter(result.error for result in failed if result.error)),
        "by_category": by_category,
    }


def ratio_on(results: list[EvaluationResult], predicate: Callable[[EvaluationResult], bool]) -> float:
    if not results:
        return 0.0
    return sum(1 for result in results if predicate(result)) / len(results)


def evaluate_cases(
    cases: list[SyntheticCase],
    *,
    base_url: str,
    timeout_seconds: float,
    run_id: str,
    ticket_store: TicketStoreClient | None,
) -> list[EvaluationResult]:
    results: list[EvaluationResult] = []

    for case in cases:
        try:
            shared_request = namespace_request(case.request, run_id, case.case_id, shared=True)

            if case.expected_policy_stage == "soft_rule":
                # Prime the semantic cache so the measured request can exercise the soft-policy path.
                prime_payload = deepcopy(shared_request)
                prime_payload["request_id"] = f"{shared_request['request_id']}-prime"
                post_decision(base_url, prime_payload, timeout_seconds)

                if case.ticket_present:
                    issued, skipped_reason = issue_ticket_if_possible(ticket_store, shared_request)
                    if not issued:
                        results.append(score_response(case, None, skipped=True, skipped_reason=skipped_reason))
                        continue

                eval_payload = deepcopy(shared_request)
                eval_payload["request_id"] = f"{shared_request['request_id']}-eval"
            else:
                eval_payload = namespace_request(case.request, run_id, case.case_id, shared=False)

            body = post_decision(base_url, eval_payload, timeout_seconds)
            results.append(score_response(case, body, skipped=False))
        except Exception as exc:  # noqa: BLE001
            results.append(score_response(case, None, skipped=False, error=str(exc)))

    return results


def ensure_ready(base_url: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        ready = client.get(f"{base_url}/ready")
        ready.raise_for_status()
        body = ready.json()
    if body.get("status") not in {"ready", "degraded"}:
        raise RuntimeError(f"service not ready for evaluation: {json.dumps(body, indent=2)}")


def maybe_build_ticket_store() -> TicketStoreClient | None:
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    return TicketStoreClient(enabled=True, redis_url=settings.redis_url)


def write_outputs(results: list[EvaluationResult], summary: dict, json_out: Path, csv_out: Path, metadata: dict) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps({"metadata": metadata, "summary": summary, "results": [asdict(result) for result in results]}, indent=2),
        encoding="utf-8",
    )
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "case_id",
                "category",
                "expected_policy_stage",
                "expected_decision",
                "expected_reason_code",
                "actual_decision",
                "actual_reason_code",
                "actual_decision_source",
                "actual_latency_ms",
                "actual_cost_usd",
                "actual_rationale_summary",
                "actual_rationale_facts",
                "decision_exact_match",
                "decision_family_match",
                "reason_code_match",
                "rationale_present",
                "rationale_grounded",
                "false_allow",
                "false_deny",
                "false_escalate",
                "skipped",
                "skipped_reason",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "case_id": result.case_id,
                    "category": result.category,
                    "expected_policy_stage": result.expected_policy_stage,
                    "expected_decision": result.expected_decision,
                    "expected_reason_code": result.expected_reason_code,
                    "actual_decision": result.actual_decision or "",
                    "actual_reason_code": result.actual_reason_code or "",
                    "actual_decision_source": result.actual_decision_source or "",
                    "actual_latency_ms": result.actual_latency_ms if result.actual_latency_ms is not None else "",
                    "actual_cost_usd": round(result.actual_cost_usd, 8),
                    "actual_rationale_summary": result.actual_rationale_summary or "",
                    "actual_rationale_facts": json.dumps(result.actual_rationale_facts),
                    "decision_exact_match": result.decision_exact_match,
                    "decision_family_match": result.decision_family_match,
                    "reason_code_match": result.reason_code_match,
                    "rationale_present": result.rationale_present,
                    "rationale_grounded": result.rationale_grounded,
                    "false_allow": result.false_allow,
                    "false_deny": result.false_deny,
                    "false_escalate": result.false_escalate,
                    "skipped": result.skipped,
                    "skipped_reason": result.skipped_reason,
                    "error": result.error,
                }
            )
def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the synthetic Phase A dataset through the access-control API.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--tag", default="", help="Optional label appended to timestamped output filenames.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    run_id = str(uuid4())
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    stem = f"_{args.tag}" if args.tag else ""

    # Canonical paths (overwritten each run — always point at the latest result)
    json_out = Path(args.json_out)
    csv_out = Path(args.csv_out)

    # Timestamped copies so successive runs are never lost
    ts_json_out = json_out.parent / f"{json_out.stem}{stem}_{ts}{json_out.suffix}"
    ts_csv_out = csv_out.parent / f"{csv_out.stem}{stem}_{ts}{csv_out.suffix}"

    ensure_ready(args.base_url)
    cases = load_cases(dataset_path)
    ticket_store = maybe_build_ticket_store()
    results = evaluate_cases(
        cases,
        base_url=args.base_url,
        timeout_seconds=args.request_timeout_seconds,
        run_id=run_id,
        ticket_store=ticket_store,
    )
    summary = summarize(results)
    metadata = {
        "dataset": str(dataset_path),
        "base_url": args.base_url,
        "request_timeout_seconds": args.request_timeout_seconds,
        "run_id": run_id,
        "tag": args.tag,
    }
    write_outputs(results, summary, json_out, csv_out, metadata)
    write_outputs(results, summary, ts_json_out, ts_csv_out, metadata)
    print(json.dumps({"metadata": metadata, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
