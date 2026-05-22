# Pipeline Architecture — LLM Semantic Access Control

> **Source of truth:** `app/pipeline.py` — `AccessPipeline.decide()`.  
> This document describes the *implemented* system. For the early conceptual design, see `data_flow.md` / `dataflow.md`.

---

## 1. Overview

Every `POST /v1/access/decide` call executes a single `AccessPipeline.decide(req)` call.
The pipeline is **short-circuit sequential**: a stage returns a final `AccessResponse` as soon
as it produces a definitive outcome. Later stages are only reached if all earlier stages pass.

```
AccessRequest
    │
    ├─[1] Hard Policy (OPA)         → DENY on clearance / role / MFA / session
    │
    ├─[2] Threat Screening          → DENY on embedding similarity to attack patterns
    │
    ├─[3] Cache Lookup (Qdrant)
    │       ├─ sim ≥ t_hit          → [3a] Soft Re-eval → ALLOW_CACHE  (or fall to LLM)
    │       ├─ t_low ≤ sim < t_hit  → [4]  Cross-Encoder → ALLOW_CACHE (or fall to LLM)
    │       └─ miss                 → [5]  LLM path
    │
    ├─[5] Soft Policy (OPA)         → ESCALATE_HUMAN on out-of-hours (deterministic)
    │                                  fall-through on incident/sensitivity (LLM decides)
    │
    ├─[6] LLM Decision              → propose ALLOW / DENY / ESCALATE_HUMAN
    │
    ├─[7] Policy Veto (OPA)         → override LLM if it violates a hard rule
    │
    └─ _finalize() → AccessResponse + audit event + cache update
```

---

## 2. Request / Response Contract

### AccessRequest (input)

```json
{
  "request_id": "uuid",
  "timestamp_utc": "ISO-8601",
  "user": {
    "user_id": "string",
    "role": "analyst | engineer | manager | executive | auditor | security | support",
    "department": "string",
    "region": "string",
    "clearance_level": 1
  },
  "context": {
    "ip_address": "string",
    "device_id": "string",
    "session_id": "string",
    "mfa_state": "passed | failed | unknown",
    "incident_state": "normal | elevated | critical"
  },
  "resource": {
    "resource_type": "dashboard | report | table | api | document",
    "resource_id": "string",
    "sensitivity": "public | internal | restricted | confidential"
  },
  "query": {
    "prompt": "string",
    "purpose": "string"
  }
}
```

### AccessResponse (output)

```json
{
  "request_id": "uuid",
  "decision": "ALLOW | ALLOW_CACHE | ALLOW_EMERGENCY | DENY | ESCALATE_HUMAN",
  "decision_source": "hard_rule | cache | validation | llm | threat_gate",
  "reason_code": "string",
  "confidence": 0.0,
  "rationale": { "step1": "string", "step2": "string", "final": "string" },
  "scores": {
    "cache_similarity": null,
    "cross_encoder_score": null,
    "threat_similarity": null
  },
  "policy_version": "string",
  "mode": "performance | balanced | conservative",
  "latency_ms": 0,
  "llm_usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
  "estimated_cost_usd": 0.0
}
```

---

## 3. Stage-by-Stage Detail

### Stage 1 — Hard Policy (OPA/Rego) · `pipeline.py:63`

- **Trigger:** every request except `ablation_mode = "llm_only"`
- **Engine:** OPA evaluates `policies/hard.rego`
- **Rules (H1–H4):**
  - H1 MFA — `mfa_state != "passed"` on restricted/confidential → DENY
  - H2 Session — `session_id` invalid → DENY
  - H3 Clearance — `clearance_level < sensitivity_minimum` → DENY
  - H4 Role-Resource — role not in allowed roles for resource_type → DENY
- **On DENY:** returns immediately; downstream stages never execute.
- **Reason codes:** `MFA_REQUIRED`, `SESSION_INVALID`, `CLEARANCE_TOO_LOW`, `ROLE_RESOURCE_DENIED`
- **Latency:** sub-millisecond OPA evaluation (no network call in embedded mode)

---

### Stage 2 — Threat Screening · `pipeline.py:77`

- **Input:** 384-dim normalized embedding from `EmbeddingService.encode(req.query.prompt)`
- **Operation:** cosine similarity against a Qdrant collection of known attack patterns
- **Threshold:** `t_attack` (mode-dependent, default 0.85)
- **On match:** returns `DENY`, `source=threat_gate`, `reason_code=THREAT_PATTERN_MATCH`
- **Note:** embedding is computed once here (`pipeline.py:76`) and reused in all subsequent stages

---

### Stage 3 — Semantic Cache Lookup · `pipeline.py:93`

- **Skipped when:** `ablation_mode ∈ {no_cache, llm_only}`
- **Vector store:** Qdrant, collection filtered by `role`, `clearance_level`, `resource_type`, `policy_version`
- **Similarity metric:** cosine similarity between query embedding and cached prompt embedding
- **Routing by `S_cache`:**

| Score range | Path |
|---|---|
| `S_cache ≥ t_hit` | Direct cache hit → `_handle_cache_hit(source=cache)` |
| `t_validate_low ≤ S_cache < t_hit` | Validation band → cross-encoder → `_handle_cache_hit(source=validation)` or LLM |
| `S_cache < t_validate_low` | Cache miss → LLM path |

#### Stage 3a — Soft Policy Re-evaluation · `pipeline.py:145`

Called inside `_handle_cache_hit()` **on every cache hit**, regardless of similarity score.

- **Evaluates:** `incident_state` (normal/elevated/critical), time-window restrictions
- **On pass:** returns `ALLOW_CACHE`, `reason_code=CACHE_HIT_SOFT_PASS`
- **On fail:** falls through to LLM path (the cached ALLOW is not served)
- **Emergency branch:** if soft fails but `ticket_store.has_ticket(user_id, resource_id)` → `ALLOW_EMERGENCY`
- **Safety guarantee:** no stale ALLOW can be served from cache if security context changed
- **Skipped when:** `ablation_mode = "no_cache_reeval"` — ablation A1 (100% false-allow on near-miss)

#### Stage 4 — Cross-Encoder Validation · `pipeline.py:98`

Only reached when `t_validate_low ≤ S_cache < t_hit`.

- **Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Input:** `(req.query.prompt, candidate.cached_text)` pair
- **Threshold:** `VALIDATION_THRESHOLD` (default 0.80)
- **On hit:** `_handle_cache_hit(source=validation)` — soft re-eval still runs
- **On miss:** falls to LLM path, cross-encoder score forwarded in `AccessScores`

---

### Stage 5 — Soft Policy Pre-check (LLM path) · `pipeline.py:182`

Before invoking the LLM, soft policy is evaluated to handle deterministic cases:

- `OUT_OF_HOURS_FAST_PATH_REVIEW` → return `ESCALATE_HUMAN` immediately (no LLM needed)
- `INCIDENT_CRITICAL` or `elevated+confidential` → fall through to LLM (LLM may grant `ALLOW_EMERGENCY`)
- Emergency ticket check: `has_ticket()` → return `ALLOW_EMERGENCY` without LLM

---

### Stage 6 — LLM Decision · `pipeline.py:212`

- **Backends:** OpenAI (`gpt-4o-mini` default) or vLLM (configurable via `VLLM_BASE_URL`)
- **Prompt structure:** two-step chain-of-thought
  - Step 1: evaluate hard rules H1–H4 explicitly
  - Step 2: evaluate escalation conditions S1 (critical incident) and S2 (elevated + confidential)
- **Output:** structured JSON — `proposed_decision`, `reason_code`, `confidence`, `rationale`
- **Fail-closed:** if LLM unavailable and `sensitivity ∈ {restricted, confidential}` → `DENY`
- **Shadow provider:** optional second LLM sampled at `shadow_sampling_rate` for A/B testing; result published to event bus only, never returned to user

---

### Stage 7 — Policy Veto · `pipeline.py:237`

- **Engine:** OPA re-evaluates hard rules against the LLM's proposed decision
- **Purpose:** catch LLM hallucinations that violate deterministic policy
- **On veto:** reason code prefixed `VETO_` (e.g. `VETO_CLEARANCE_TOO_LOW`)
- **Emergency ticket issuance:** if LLM proposes `ALLOW_EMERGENCY` and veto passes → `ticket_store.issue_ticket(ttl=900s)`

---

### Stage 8 — Finalize & Emit · `pipeline.py:280`

`_finalize()` is called by every decision path:

1. Builds `AccessResponse` with latency, scores, rationale
2. Publishes `audit.events` (always)
3. Publishes `cache.update` — **only if** `decision != ESCALATE_HUMAN`
   - ESCALATE_HUMAN decisions are never written to cache (prevents contamination)
   - If event bus disabled: `_write_cache_update_sync()` — direct Qdrant upsert with dynamic TTL
4. Publishes `feedback.events` for attack pattern refresh

---

## 4. Operating Modes and Thresholds

Thresholds are adjusted at runtime via `POST /v1/admin/mode` without restart.

| Mode | `t_hit` | `t_validate_low` | `t_attack` | Behavior |
|---|:---:|:---:|:---:|---|
| `performance` | 0.80 | 0.65 | 0.88 | Maximum cache reuse |
| `balanced` | 0.85 | 0.70 | 0.85 | Default production posture |
| `conservative` | 0.93 | 0.78 | 0.80 | More cross-encoder + more LLM |

Threshold sweep evaluation (Phase B benchmark) confirmed that cache precision = 1.0 and false-allow rate = 0.0% across all six tested modes (t_hit ∈ {0.80, 0.85, 0.88, 0.90, 0.93, 0.95}) when soft re-evaluation is enabled.

---

## 5. Ablation Modes

Togglable at runtime via `POST /v1/admin/ablation` without restart.

| Mode | Code | What is disabled | Used in |
|---|---|---|---|
| Full pipeline | `none` | — (default) | Baseline |
| A1 | `no_cache_reeval` | Soft re-evaluation on cache hits | Phase B near-miss test |
| A2 | `no_cache` | Semantic cache + cross-encoder entirely | Phase A accuracy test |
| A3 | `llm_only` | Hard policy pre-gate + cache | Phase A accuracy test |

**A1 effect:** cache precision 1.0 → 0.552; 100% false-allow on near-miss variants (24 incident + 15 elevated+confidential cases).

---

## 6. Decision Source Map

| `decision_source` | Stage that produced it | Typical latency |
|---|---|---|
| `hard_rule` | Stage 1 (OPA hard) or Stage 5 (out-of-hours fast path) | < 5 ms |
| `threat_gate` | Stage 2 | ~70 ms (embedding) |
| `cache` | Stage 3a (direct hit, sim ≥ t_hit) | ~71 ms p50 |
| `validation` | Stage 4 (cross-encoder hit) | ~99 ms p50 |
| `llm` | Stage 6–7 | ~2,157 ms p50 |

---

## 7. Key Invariants

1. **Embedding is computed once** (Stage 2, `pipeline.py:76`) and passed by reference to all subsequent stages.
2. **`ESCALATE_HUMAN` is never cached** (`pipeline.py:327`) — prevents future requests from inheriting an uncertain decision.
3. **Soft re-evaluation runs in both paths** — inside `_handle_cache_hit()` (cache path) and at the start of `_llm_path()` (LLM path). There is no way to get `ALLOW_CACHE` without passing soft policy.
4. **LLM is only invoked when necessary** — hard rules (35.6%) and cache hits (27.6%) are resolved without LLM. LLM is called for 36.8% of requests in production baseline.
5. **Fail-closed on LLM failure** — if the LLM call fails and `sensitivity ∈ {restricted, confidential}`, the response is `DENY`. For public/internal resources, the error propagates.

---

## 8. Dynamic TTL

Cache entries use a dynamic TTL computed by `app/ttl.py:compute_dynamic_ttl()`:

```
TTL = base_ttl(role, sensitivity) × confidence_factor × policy_stability_factor
```

- Minimum: 5 minutes
- Maximum: 24 hours (public/internal), 2 hours (confidential)
- Immediate logical expiry on policy version change (version stored in cache payload)
- `expires_at_ts` stored in Qdrant payload; cache lookup filters `expires_at_ts > now()`

---

## 9. Infrastructure Dependencies

| Service | Role | Opt-in env var | Fallback |
|---|---|---|---|
| OPA | Hard + soft + veto policy | `OPA_ENABLED` | Inline Python evaluation (subset) |
| Qdrant | Vector cache + threat patterns | `QDRANT_ENABLED` | Skip cache, go to LLM |
| Redis | Emergency ticket store | `REDIS_ENABLED` | Disable emergency bypass |
| Kafka | Async audit + cache update | `KAFKA_ENABLED` | Synchronous Qdrant write |
| OpenAI / vLLM | LLM decision | `OPENAI_API_KEY` / `VLLM_BASE_URL` | Fail-closed on sensitive resources |

All external dependencies are opt-in. The pipeline degrades gracefully when a service is unavailable, always biasing toward denial for sensitive resources.
