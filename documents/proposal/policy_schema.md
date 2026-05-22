# Policy Schema Design

## 1. Purpose

This document defines the policy-layer schema used by the access-control system.

The policy layer has three responsibilities:

1. Evaluate deterministic hard rules before any semantic or LLM path.
2. Evaluate deterministic soft rules on cache and validation hits.
3. Apply final veto and normalization to LLM-proposed decisions.

The current implementation is defined by:

- [app/clients/policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py)
- [policies/hard.rego](/d:/Study%20Documents/Other%20subjects/LLM_AC/policies/hard.rego)
- [policies/soft.rego](/d:/Study%20Documents/Other%20subjects/LLM_AC/policies/soft.rego)
- [app/pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py)
- [app/models.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/models.py)

## 2. Policy Architecture

The policy layer is split into three logical stages:

1. `hard_allow`
2. `soft_allow`
3. `veto`

Execution order in the pipeline:

1. Hard rules run first.
2. If hard rules deny, the request ends immediately with `DENY`.
3. If cache or validation hits, soft rules run before returning `ALLOW_CACHE`.
4. If the request reaches the LLM path, the LLM proposal is post-processed by `veto`.

Pipeline call sites:

- hard rules: [pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py:58)
- soft rules: [pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py:123)
- veto: [pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py:184)

## 3. Canonical Policy Input Schema

Both OPA policies receive the full `AccessRequest` object as `input`.

Canonical shape:

```json
{
  "request_id": "req-123",
  "timestamp_utc": "2026-04-09T10:00:00Z",
  "user": {
    "user_id": "u-1",
    "role": "analyst",
    "department": "finance",
    "region": "us",
    "clearance_level": 2
  },
  "context": {
    "ip_address": "10.1.1.1",
    "device_id": "dev-1",
    "session_id": "sess-1",
    "mfa_state": "passed",
    "incident_state": "normal"
  },
  "resource": {
    "resource_type": "document",
    "resource_id": "doc-42",
    "sensitivity": "internal"
  },
  "query": {
    "prompt": "Need access to quarterly finance report",
    "purpose": "monthly close"
  }
}
```

Model source:

- [models.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/models.py:72)

## 4. Canonical Policy Output Schema

Both `hard_allow` and `soft_allow` return the same logical result shape:

```json
{
  "allow": true,
  "reason_code": "HARD_POLICY_PASS",
  "matched_rule": "default_allow"
}
```

This maps directly to:

```python
class PolicyResult(BaseModel):
    allow: bool
    reason_code: str
    matched_rule: str | None = None
```

Source:

- [models.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/models.py:132)

Semantics:

1. `allow`
   - final boolean result for that policy stage
2. `reason_code`
   - stable application-facing explanation code
3. `matched_rule`
   - concrete rule identifier used for debugging and auditability

## 5. OPA Transport Contract

When OPA is enabled, the client sends requests as:

```json
{
  "input": {
    "... full AccessRequest payload ..."
  }
}
```

Transport implementation:

- [policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py:16)

Current OPA endpoints:

1. `POST /v1/data/access/hard_allow`
2. `POST /v1/data/access/soft_allow`

Expected OPA response:

```json
{
  "result": {
    "allow": true,
    "reason_code": "HARD_POLICY_PASS",
    "matched_rule": "default_allow"
  }
}
```

## 6. Hard Policy Schema

### 6.1 Role

Hard policy is the fail-fast deterministic gate.

If hard policy denies, the pipeline returns:

- `decision = DENY`
- `decision_source = hard_rule`

Source:

- [pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py:58)

### 6.2 Current Hard Rules

Implemented fallback logic:

- [policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py:22)

Implemented Rego:

- [hard.rego](/d:/Study%20Documents/Other%20subjects/LLM_AC/policies/hard.rego:1)

Current rules:

1. Deny if `context.mfa_state != "passed"`
   - `reason_code = MFA_REQUIRED`
   - `matched_rule = mfa_required`

2. Deny if `context.session_id == ""`
   - `reason_code = SESSION_INVALID`
   - `matched_rule = session_required`

3. Allow otherwise
   - `reason_code = HARD_POLICY_PASS`
   - `matched_rule = default_allow`

### 6.3 Hard Policy Output Examples

MFA failure:

```json
{
  "allow": false,
  "reason_code": "MFA_REQUIRED",
  "matched_rule": "mfa_required"
}
```

Session missing:

```json
{
  "allow": false,
  "reason_code": "SESSION_INVALID",
  "matched_rule": "session_required"
}
```

Pass:

```json
{
  "allow": true,
  "reason_code": "HARD_POLICY_PASS",
  "matched_rule": "default_allow"
}
```

## 7. Soft Policy Schema

### 7.1 Role

Soft policy is evaluated only after a semantic cache hit or validation hit.

It is not the primary hard gate. It is a contextual safety gate for fast-path reuse.

If soft policy allows:

- cache/validation can return `ALLOW_CACHE`

If soft policy denies:

1. the system checks for an emergency ticket
2. if no ticket exists, the request falls through to the LLM path

Source:

- [pipeline.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/pipeline.py:123)

### 7.2 Current Soft Rules

Implemented fallback logic:

- [policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py:37)

Implemented Rego:

- [soft.rego](/d:/Study%20Documents/Other%20subjects/LLM_AC/policies/soft.rego:1)

Current rules:

1. Deny if `context.incident_state == "critical"`
   - `reason_code = INCIDENT_CRITICAL`
   - `matched_rule = incident_guard`

2. Allow otherwise
   - `reason_code = SOFT_POLICY_PASS`
   - `matched_rule = default_allow`

### 7.3 Soft Policy Output Examples

Critical incident:

```json
{
  "allow": false,
  "reason_code": "INCIDENT_CRITICAL",
  "matched_rule": "incident_guard"
}
```

Pass:

```json
{
  "allow": true,
  "reason_code": "SOFT_POLICY_PASS",
  "matched_rule": "default_allow"
}
```

## 8. Veto Schema

### 8.1 Role

The veto stage applies deterministic post-processing to an LLM proposal.

It does not call OPA directly as a separate endpoint. It is implemented in application code inside `OPAClient.veto(...)`.

Source:

- [policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py:50)

### 8.2 Veto Input Schema

Inputs:

1. full `AccessRequest`
2. `proposed: Decision`

Allowed proposal values:

- `ALLOW`
- `DENY`
- `ESCALATE_HUMAN`
- `ALLOW_CACHE`
- `ALLOW_EMERGENCY`

Decision enum source:

- [models.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/models.py:23)

### 8.3 Veto Output Schema

Return type:

```python
tuple[Decision, str]
```

Meaning:

1. normalized or vetoed final decision
2. veto reason string

### 8.4 Current Veto Rules

1. Re-run hard policy.
2. If hard policy denies:
   - return `(DENY, "VETO_<hard_reason_code>")`

3. If the proposal is `ALLOW_CACHE` or `ALLOW_EMERGENCY`:
   - normalize to `(ALLOW, "VETO_NORMALIZED_ALLOW")`

4. Otherwise:
   - pass through `(proposed, "VETO_PASS")`

This means the LLM never returns `ALLOW_CACHE` as the final outward decision. Cache-specific decisions are normalized to ordinary `ALLOW` during the veto stage.

## 9. Fallback Behavior When OPA Is Disabled

OPA is optional at runtime.

If `OPA_ENABLED=false`, the client uses local fallback logic that mirrors the sample Rego behavior.

This is implemented in:

- [policy_client.py](/d:/Study%20Documents/Other%20subjects/LLM_AC/app/clients/policy_client.py:22)

Current fallback parity:

1. Hard fallback matches `hard.rego`
2. Soft fallback matches `soft.rego`

This makes the local development path behaviorally similar to the OPA-backed path for the current rule set.

## 10. Policy Reason-Code Schema

Current reason codes in the policy layer:

### 10.1 Hard Policy

1. `MFA_REQUIRED`
2. `SESSION_INVALID`
3. `HARD_POLICY_PASS`

### 10.2 Soft Policy

1. `INCIDENT_CRITICAL`
2. `SOFT_POLICY_PASS`

### 10.3 Veto Layer

1. `VETO_<hard_reason_code>`
2. `VETO_NORMALIZED_ALLOW`
3. `VETO_PASS`

These reason codes are used for:

1. response explanations
2. audit payloads
3. debugging benchmark outcomes

## 11. Policy Decision Matrix

### 11.1 Hard Policy Matrix

| Condition | Result |
|---|---|
| MFA not passed | deny |
| session missing | deny |
| otherwise | allow |

### 11.2 Soft Policy Matrix

| Condition | Result |
|---|---|
| incident state = critical | deny |
| otherwise | allow |

### 11.3 Veto Matrix

| Condition | Result |
|---|---|
| hard policy denies | final `DENY` |
| proposed = `ALLOW_CACHE` | normalize to `ALLOW` |
| proposed = `ALLOW_EMERGENCY` | normalize to `ALLOW` |
| otherwise | pass through |

## 12. Policy Data Dependencies

The current policy layer depends on these request fields:

### 12.1 Hard Policy Fields

1. `context.mfa_state`
2. `context.session_id`

### 12.2 Soft Policy Fields

1. `context.incident_state`

### 12.3 Veto Fields

1. full request, because hard policy is re-evaluated
2. proposed decision

This is a deliberately small schema surface. It keeps deterministic policy simple while leaving richer contextual reasoning to the semantic and LLM layers.

## 13. Current Strengths

The current policy schema is strong in these ways:

1. Small and explicit contract
2. Clear split between hard rules, soft rules, and veto
3. OPA-compatible transport shape
4. Stable reason codes
5. Local fallback path for development
6. Deterministic override of unsafe LLM behavior through hard-rule veto

## 14. Current Limitations

The current policy schema is intentionally minimal.

Known limitations:

1. Hard policy only checks MFA and session presence
2. Soft policy only checks critical incident state
3. No explicit policy version is returned by OPA policy itself
4. Veto logic lives in application code, not Rego
5. No structured deny details beyond `reason_code` and `matched_rule`
6. No direct policy support yet for role-resource sensitivity mapping
7. No explicit IP, device, or geo anomaly policy

## 15. Recommended V2 Policy Schema

If the system evolves, the next policy schema should add:

1. richer hard checks
   - blocked roles
   - blocked IP ranges
   - sensitivity vs clearance mapping
   - session freshness
   - device trust state

2. richer soft checks
   - elevated incident states
   - temporary risk-based throttles
   - geo or department exceptions

3. structured policy result metadata

Example V2 policy result:

```json
{
  "allow": false,
  "reason_code": "CLEARANCE_TOO_LOW",
  "matched_rule": "sensitivity_clearance_guard",
  "severity": "high",
  "policy_domain": "hard",
  "explanations": [
    "resource sensitivity exceeds user clearance"
  ]
}
```

4. externalized veto rules in OPA or a dedicated policy layer if normalization logic grows

## 16. Summary

The implemented policy schema is a layered deterministic control plane:

1. `hard_allow` for fail-fast deny decisions
2. `soft_allow` for fast-path cache gating
3. `veto` for deterministic control over LLM proposals

The current schema is intentionally small, but it is coherent and aligned with the pipeline:

1. hard rules protect the front door
2. soft rules protect fast reuse paths
3. veto protects the final LLM output

For the current MVP, this is a reasonable schema. The next meaningful evolution is richer policy coverage and more structured policy result metadata.
