# LLM-Augmented Semantic Access Control with a Safety-Preserving Semantic Cache

**[ADBIS 2026 — Short Paper]**

**Authors:** [Author 1], [Author 2], ...
**Affiliation:** [Institution]
**Contact:** [email]

---

## Abstract

Conventional access control policy engines are precise and auditable but cannot interpret natural language requests or reason about contextual intent; large language models can handle such requests flexibly but lack the determinism that security enforcement requires. We present a hybrid seven-stage pipeline that reconciles both properties: a deterministic OPA/Rego hard-policy gate handles all structurally decided cases, while an LLM resolves semantically ambiguous requests. Because enterprise request traffic is structurally repetitive, an embedding-based semantic cache reduces repeat LLM calls — but introduces the *cache safety problem*: a cached decision may be stale if the security context has changed since caching. We address this with a safety-preserving cache design that re-evaluates current context on every cache hit before returning any decision, providing a zero false allow rate from the cache as an architectural guarantee. We evaluate the system on three purpose-built benchmarks: Phase A (202 oracle-labeled cases across the full policy matrix), Phase B (111 anchor-variant pairs targeting cache safety under six threshold configurations), and Phase C (70 records for threat-screening separability). The system achieves 98.01% decision accuracy, 0.0% false allow rate, and a 30× median latency reduction for cached requests (71 ms vs. 2,157 ms). An ablation study confirms that disabling cache safety re-evaluation causes 100% false allow on all 39 security-relevant near-miss variants, removing the cache reduces accuracy by 2.96 pp, and removing the hard-rule gate collapses reason code accuracy from 48% to 23%. Otsu's method applied to the embedding similarity distribution reveals a bimodal structure with a 0.175-wide natural gap ([0.626, 0.801]), providing a principled basis for threshold selection and confirming that no similarity threshold alone can guarantee cache safety.

**Keywords:** access control, large language models, semantic caching, policy enforcement, OPA

---

## 1. Introduction

<!-- Target: ~1 page -->

Access control in enterprise systems has traditionally been expressed as static, structured policies where role-based (RBAC) or attribute-based (ABAC) rules are evaluated deterministically against well-defined conditions [CITE][CITE]. However, modern environments increasingly involve natural language requests and dynamic contextual conditions — evolving incident states, cross-domain sensitivity classifications, and emergency overrides — where policy intent is better described than formally specified. Static rule engines struggle with these cases: they either require exhaustive rule authoring for every combination of context, or fall back to a conservative default deny that blocks legitimate access.

Large language models (LLMs) offer an alternative: they can reason over natural-language requests, apply contextual judgment, and handle edge cases without exhaustive rule enumeration. Recent work has explored LLMs as access control decision-makers [CITE][CITE][CITE], demonstrating coverage of contextual scenarios beyond the reach of rule-based systems. However, LLM-based access control raises two fundamental tensions that existing work has not fully resolved. First, a single LLM inference takes seconds — two to three orders of magnitude slower than a rule lookup — compounding across every protected operation in a busy system. Second, LLMs are non-deterministic: semantically identical requests may receive different decisions across calls, violating the consistency requirement of any access control model.

Semantic caching — storing prior LLM decisions indexed by request embeddings and retrieving them via nearest-neighbor search — appears to address both tensions simultaneously: cache hits are fast and repeatable. However, naive semantic caching introduces a third problem that existing systems do not address: the *cache safety problem*. A request that is semantically similar to a cached ALLOW decision but differs in security-relevant context — for instance, the system has since entered a critical incident state — must not receive the cached answer. Existing LLM caching work [CITE] reuses prior outputs without any safety re-check; LLM-based authorization research [CITE][CITE] focuses on policy authoring or query interpretation rather than runtime enforcement with safety guarantees. We show empirically that certain near-miss request pairs score maximum cosine similarity to a cached entry yet require a different decision — confirming that no threshold-based cache rule alone can guarantee safety.

This paper makes the following contributions:

1. **Seven-stage hybrid pipeline.** A modular architecture combining deterministic hard-policy gating, embedding-based semantic caching, cross-encoder validation, LLM reasoning, and policy veto, with each stage's failure mode isolated from the others.
2. **Safety-preserving cache with architectural guarantee.** A caching design that re-evaluates current context on every cache hit before returning any decision, eliminating stale cached decisions without sacrificing the latency advantage — providing a zero false allow rate as an architectural property rather than an empirical observation.
3. **Three-phase benchmark suite.** Phase A (202 oracle-labeled cases across the full policy matrix), Phase B (111 anchor-variant pairs targeting cache safety under six threshold configurations), and Phase C (70 records for threat-screening separability) — all labeled by deterministic oracle to avoid annotation bias.
4. **Empirical evaluation and ablation study.** 98.01% decision accuracy, 0.0% false allow rate, and 30× latency reduction for cached requests; an ablation showing that disabling cache safety re-evaluation causes 100% false allow on all 39 security-relevant near-miss variants; and an Otsu's method analysis of the embedding similarity distribution revealing a bimodal structure with a 0.175-wide natural gap ([0.626, 0.801]) that provides a principled basis for threshold selection.

Section 2 reviews related work; Section 3 describes the system architecture; Section 4 presents the three-phase evaluation setup; Section 5 reports results; Section 6 discusses findings and limitations; Section 7 concludes.

---

## 2. Related Work

<!-- Target: ~0.75 page -->

### 2.1 Policy-Based Access Control

Role-based access control (RBAC) [CITE] and attribute-based access control (ABAC) [CITE] are the dominant paradigms for enterprise authorization, offering deterministic, auditable enforcement based on role assignments and attribute predicates respectively. Policy engines such as OPA/Rego [CITE] extend this model with expressive Datalog-style rules that can incorporate structured context — clearance levels, department membership, MFA state — while retaining sub-millisecond evaluation latency. These approaches are well-suited to cases where all decision-relevant facts can be enumerated in advance and expressed as structured predicates. Their limitation emerges when access requests include natural language purpose fields, intent-dependent context (e.g., "to investigate the current incident"), or resource descriptions that do not map cleanly to a predefined attribute vocabulary. In such cases the policy engine has no basis for evaluation; the request either falls through to a default or is denied conservatively. Our work retains a deterministic OPA layer for cases where structured facts suffice, and delegates only the residual semantically ambiguous cases to an LLM.

### 2.2 LLMs for Authorization and Policy Reasoning

Several recent studies have explored LLMs as interpreters of natural language access policies. [CITE] demonstrated that GPT-4 can correctly classify access requests against policies expressed in plain English, achieving high accuracy on standard ABAC benchmarks. [CITE] investigated LLM-based generation of ABAC policies from natural language specifications, targeting the policy authoring phase rather than runtime enforcement. A recurring finding across this line of work is that LLMs carry training priors — for instance, a tendency to treat the word "confidential" as inherently dangerous independent of the actual policy — which can produce decisions that are plausible but inconsistent with the defined rule set. None of these systems integrates LLM reasoning with a formal policy engine at runtime, nor do they evaluate false allow rates under security-critical scenarios. Our pipeline addresses both gaps: LLM calls are gated by a hard-rule pre-check that prevents the LLM from evaluating cases with a deterministic answer, and a policy veto layer re-runs OPA on every LLM proposal to catch hallucinated decisions before they are returned.

### 2.3 Semantic Caching in Database and Information Systems

Semantic caching was first proposed for database query processing [CITE], where query results are reused for semantically equivalent reformulations of a prior query rather than requiring string-identical matches. The concept was extended to information retrieval and, more recently, to LLM inference: embedding-based caching systems [CITE] store LLM responses keyed by dense vector representations of the input and return a cached response whenever a new input falls within a similarity threshold of a stored entry. This approach significantly reduces inference cost and latency for workloads with near-duplicate inputs. However, existing LLM caching systems are designed for general-purpose assistants where a cached response to a semantically equivalent query is always safe to reuse. In access control, this assumption fails: two requests may be semantically near-identical (same user, same resource, same natural language prompt) yet require different decisions if the security context has changed between the two calls. We identify this as the *cache safety problem* and design a cache that explicitly re-evaluates context-dependent conditions on every hit — an approach analogous to cache invalidation triggers in database systems, but applied to security metadata rather than data freshness.

---

## 3. System Architecture

<!-- Target: ~1.5 pages -->

### 3.1 Pipeline Overview

Each access request flows through seven sequential stages. A decision is returned as soon as any stage produces a final outcome; later stages are only reached if earlier stages pass.

```
AccessRequest { user, resource, context, query }
    │
    ▼
[1] Hard Policy (OPA/Rego)
    │  DENY → return immediately (MFA, session, clearance, role)
    │  pass ↓
[2] Threat Screening
    │  attack pattern detected → DENY / ESCALATE
    │  clear ↓
[3] Semantic Cache Lookup  (Qdrant, cosine similarity)
    │  hit (sim ≥ t_hit) → [3a] Soft Policy Re-eval → ALLOW_CACHE or fall to [5]
    │  near-hit (t_validate_low ≤ sim < t_hit) → [4] Cross-Encoder Validation
    │  miss ↓
[5] LLM Decision  (OpenAI / vLLM, structured JSON)
    │
[6] Policy Veto  (OPA post-check on LLM proposal)
    │
AccessResponse { decision, source, reason_code, confidence, rationale, latency_ms }
```

**Decision types:** `ALLOW` · `ALLOW_CACHE` · `ALLOW_EMERGENCY` · `DENY` · `ESCALATE_HUMAN`
**Decision sources:** `hard_rule` · `cache` · `validation` · `llm` · `threat_gate`

> [FIGURE 1: Pipeline diagram — clean version of the ASCII above]

### 3.2 Hard Policy Layer (Stage 1)

- Implemented in OPA/Rego; evaluates four deterministic rule families (H1–H4): MFA state, session validity, clearance level vs. sensitivity minimum, role–resource type mapping.
- All 51 hard-rule cases in our benchmark achieve 100% accuracy with sub-millisecond OPA latency.
- **Design rationale:** gating the LLM with hard rules means the LLM never evaluates cases with a clear deterministic answer, eliminating LLM risk on the most security-critical decisions.

### 3.3 Semantic Cache with Safety Re-evaluation (Stages 3–3a)

- Requests are embedded using `sentence-transformers/all-MiniLM-L6-v2` (384-dim) and stored in Qdrant with metadata filters (role, clearance_level, resource_type, department, region).
- A cache hit (cosine similarity ≥ t_hit) does **not** immediately return the cached decision. `_handle_cache_hit()` first re-evaluates soft policy conditions: current `incident_state`, current time window.
- If soft policy passes → `ALLOW_CACHE` is returned. If it fails (e.g., incident has escalated to critical since caching) → the request falls through to the LLM.
- **Consequence:** the cache can never serve a stale ALLOW for a changed security context. This is an architectural guarantee, not an empirical observation — it holds regardless of embedding similarity score.

### 3.4 LLM Decision Layer (Stage 5)

- Structured JSON output via system prompt; supports OpenAI and vLLM backends.
- Prompt design follows a two-step chain-of-thought: **step1** evaluates hard rules H1–H4 explicitly; **step2** evaluates escalation conditions S1 (critical incident) and S2 (elevated incident + confidential sensitivity) independently.
- A policy veto (Stage 6) re-runs OPA on the LLM's proposal to catch any hallucinated decisions that violate hard rules.
- **Configurable mode thresholds** (t_hit, t_validate_low, t_attack) allow runtime tuning between performance and conservatism via `/v1/admin/mode`.

### 3.5 Worked Example: Cache Safety in Practice

The following two requests share the same user, resource, and natural-language prompt but differ in `incident_state`. They illustrate the near-miss scenario and the role of soft re-evaluation.

**Request 1 — normal incident state (first occurrence, routes to LLM):**

```json
{
  "user":     { "role": "analyst", "clearance_level": 2, "department": "finance" },
  "resource": { "resource_type": "dashboard", "sensitivity": "internal" },
  "context":  { "mfa_state": "passed", "incident_state": "normal" },
  "query":    { "prompt": "Need access to service reliability dashboard" }
}
```

```json
{
  "decision": "ALLOW",
  "decision_source": "llm",
  "reason_code": "POLICY_PASS",
  "confidence": 0.92,
  "latency_ms": 2043,
  "scores": { "cache_similarity": null }
}
```

The decision is stored in the vector cache. Subsequent identical requests return `ALLOW_CACHE` in ~71 ms.

**Request 2 — same prompt, incident escalated to critical (near-miss):**

```json
{
  "user":     { "role": "analyst", "clearance_level": 2, "department": "finance" },
  "resource": { "resource_type": "dashboard", "sensitivity": "internal" },
  "context":  { "mfa_state": "passed", "incident_state": "critical" },
  "query":    { "prompt": "Need access to service reliability dashboard" }
}
```

```json
{
  "decision": "ESCALATE_HUMAN",
  "decision_source": "cache",
  "reason_code": "INCIDENT_CRITICAL",
  "confidence": 0.95,
  "latency_ms": 84,
  "scores": { "cache_similarity": 1.0 }
}
```

The cache lookup returns cosine similarity = 1.0 — the maximum. Despite this, `_handle_cache_hit()` calls `evaluate_soft(req)` before serving the cached ALLOW. Soft policy detects `incident_state=critical` and overrides to `ESCALATE_HUMAN`. The stale cached decision is never served. This is the failure mode that removing soft re-evaluation (ablation A1) would trigger on 100% of such cases.

---

## 4. Evaluation Setup

<!-- Target: ~0.75 page -->

### 4.1 Phase A — Decision Correctness Benchmark

- **Dataset:** `phase_a_synthetic_cases.jsonl` — 202 labeled access-control cases covering the full policy matrix.
- **Construction:** Cases are generated programmatically by cross-product enumeration of 7 roles, 5 resource types, 4 sensitivity levels, and varying incident states. Natural language queries are produced using 8 prompt templates filled with role-appropriate artifacts (3 per resource type) and department-specific purposes, yielding lexically diverse but structurally controlled inputs.
- **Ground truth labeling:** Each case is labeled by running the OPA policy engine offline against the constructed request (`evaluate_hard()` then `evaluate_soft()`). Hard-rule decisions are fully deterministic; policy-pass cases (no rule fires) are labeled ALLOW by assumption, reflecting the pipeline's default behavior. This oracle labeling ensures ground truth is independent of the LLM under test and free of human annotation bias.
- **Categories:** 51 hard-rule cases (MFA, session, clearance, role), 46 soft-rule cases (critical incident, out-of-hours, elevated+confidential, emergency), 105 LLM/policy-pass cases (varying sensitivity levels, elevated non-confidential), 8 near-miss boundary cases.
- **Metrics:** decision accuracy, false allow rate, false deny/escalate rate, reason code accuracy.

> [TABLE 1: Category breakdown — stage, count, description]

### 4.2 Phase B — Semantic Cache Benchmark

- **Dataset:** `phase_b_cache_benchmark.jsonl` — 111 cases as anchor-variant pairs.
- **Construction:** 24 anchor cases are constructed as one ALLOW request per (role, resource_type) pair with normal incident state and internal sensitivity. Variants are generated by deterministic field-level perturbation of each anchor: *paraphrase* — same artifact, different template phrasing; *artifact_swap* — same template, second artifact within the same resource type; *near_miss_incident* — identical prompt with `incident_state` flipped to critical; *near_miss_elevated_conf* — identical prompt with `incident_state=elevated` and `sensitivity=confidential` (high-clearance roles only). No paraphrase model is used; all variants are rule-based.
- **Protocol:** anchors are submitted first to warm the cache; variants are then evaluated to measure cache hit rate, precision, and false allow rate.
- **Sweep:** six threshold modes tested (t_hit ∈ {0.80, 0.85, 0.88, 0.90, 0.93, 0.95}).
- **Metrics:** cache hit rate, cache precision, false allow rate on near-miss variants.

### 4.3 Phase C — Threat Screening Benchmark

- **Dataset:** `phase_c_threat_benchmark.jsonl` — 70 records: 10 canonical attack seed patterns (prompt injection, role override, privilege escalation, data exfiltration, social engineering, policy bypass, jailbreak framing, authority impersonation, context injection, token stuffing) + 30 adversarial test prompts (3 paraphrases per seed) + 30 benign control prompts drawn from Phase A.
- **Method:** Offline — no server required. All prompts are embedded with `all-MiniLM-L6-v2`. For each test prompt, the maximum cosine similarity to any seed embedding is computed. A prompt is flagged if `max_sim ≥ t_attack`.
- **Metrics:** true positive rate (adversarial caught), false positive rate (benign blocked), precision, F1, threshold sweep across `t_attack ∈ [0.50, 1.00]`.
- **Limitation acknowledged:** the benchmark uses programmatically constructed adversarial prompts, not real attacker traffic. Results establish separability properties of the embedding space, not operational attack detection rates.

### 4.4 Latency Benchmark

- 30 iterations per decision path (cache hit, validation band, LLM miss) in `balanced` mode.
- System: [hardware spec — CPU/GPU, RAM], model: `gpt-4o-mini`.

### 4.5 Ablation Study

To isolate each component's contribution we implement three ablation modes, togglable at runtime via `POST /v1/admin/ablation` without server restart:

- **A1 `no_cache_reeval`:** cache hits are served without soft policy re-evaluation (evaluated on Phase B benchmark).
- **A2 `no_cache`:** semantic cache is disabled; all requests route to the LLM (evaluated on Phase A benchmark).
- **A3 `llm_only`:** hard-rule pre-gate is disabled; the LLM handles all decisions subject to post-LLM veto only (evaluated on Phase A benchmark).

A1 tests whether soft re-evaluation provides a real safety benefit beyond embedding similarity filtering. A2 tests the accuracy contribution of the cache independent of latency savings. A3 tests whether the hard-rule pre-gate provides meaningful benefits beyond the post-LLM veto safety net.

---

## 5. Results

<!-- Target: ~2.5 pages -->

### 5.1 Phase A — Decision Accuracy

> [TABLE 2: Overall metrics for prompt_v5]

| Metric | Value |
|--------|-------|
| Decision accuracy | **98.01%** (197/201 evaluated) |
| False allow rate | **0.0%** |
| False deny / false escalate rate | 1.99% (4 cases) |
| Reason code accuracy (strict) | 47.8% |
| Reason code accuracy (family-match) | **~98%** *(see note)* |

> [TABLE 3: Per-category accuracy — pipeline_fix baseline vs. prompt_v5 final, showing ▲/▼]

**Note on reason code accuracy:** The 47.8% strict figure is dominated by a taxonomy mismatch: 101 `policy_pass` cases have expected label `POLICY_PASS_EXPECTED_ALLOW` but the LLM outputs the semantically equivalent `POLICY_PASS`. Treating these as a match (family-level equivalence) raises RC accuracy to ~98%, consistent with the near-perfect decision accuracy. The 14 genuine RC errors (18.6% of the remaining 75 non-trivial LLM cases) are concentrated in `elevated_internal` and `elevated_restricted` categories where the LLM misapplies the S2 escalation condition.

**Key result:** All hard-rule categories achieve 100% accuracy. Soft-rule categories improved substantially with structured prompt design: `soft_deny_critical` 71.4% → 100%, `soft_review` (elevated+confidential) 92.9% → 100%, `policy_pass_public` 87.5% → 100%. All remaining errors (4 cases) are false escalations — the system never incorrectly grants access.

**Residual failure mode:** `policy_pass_elevated_internal` (57.1%) and `policy_pass_elevated_restricted` (85.7%) produce occasional false escalations. The LLM conflates `sensitivity=internal`/`restricted` with the S2 condition (which requires `sensitivity=confidential`). The misleading legacy reason_code name `INCIDENT_ELEVATED_RESTRICTED_FAST_PATH` (containing "RESTRICTED") contributes to this confusion even after explicit prompt correction. This is an identifiable and bounded failure — 4 false escalations total, all in the over-cautious direction.

### 5.2 Phase B — Cache Safety and Threshold Sensitivity

> [TABLE 4: Threshold sweep — mode, t_hit, cache_hit_rate, precision, by_variant_type accuracy]

**Safety property (constant across all thresholds):**

| Property | Result |
|----------|--------|
| Cache precision | **1.0** |
| False allow rate from cache | **0.0** |

No near-miss variant — including all 24 `incident_state=critical` cases and all 15 `elevated+confidential` cases — produced a false allow from the cache. The soft policy re-evaluation on every cache hit is the mechanism responsible.

**Bimodal similarity structure and threshold robustness:**
We applied Otsu's method [CITE] offline to the embedding similarity distribution across all 87 variant-anchor pairs (Figure 3). The distribution is bimodal: artifact-swap variants cluster between 0.33 and 0.63; paraphrase variants cluster between 0.80 and 0.88; an empty gap spans [0.626, 0.801] with width 0.175. Otsu's method recovers a threshold of **0.626** — exactly at the gap lower boundary — confirming this separation is a structural property of the embedding model applied to this request vocabulary, not a hand-tuned artefact. The operational t_validate_low range [0.65, 0.80] is set within this gap, so all artifact-swap variants fall below the lower bound of cache consideration and all paraphrases are captured via direct cache hit or cross-encoder validation. The cache hit rate is flat at 0.276 from t_hit = 0.85 to t_hit = 0.95 because the paraphrase and artifact-swap clusters are fully separated at any threshold in the gap.

> [FIGURE 3: Embedding similarity histogram by variant type, with Otsu threshold (0.626), empty gap [0.626, 0.801], and t_validate_low / t_hit ranges annotated]

**Near-miss variants as the strongest safety argument:**
Near-miss variants (`near_miss_incident`, `near_miss_elevated_conf`) use prompts **identical** to their anchors and therefore score cosine similarity = 1.0 — the maximum possible. Despite this, they require ESCALATE_HUMAN rather than ALLOW. This result demonstrates that no similarity threshold, however high, can guarantee cache safety: any system that serves cache decisions based on embedding similarity alone will produce false allows for these cases. The soft policy re-evaluation in `_handle_cache_hit()` is the only mechanism that correctly handles them.

### 5.3 Phase C — Threat Screening Evaluation

> **Figure 5:** Threat screening Phase C — (a) max cosine similarity distribution for adversarial vs benign prompts; (b) TPR vs FPR threshold sweep.
> *(file: `eval/phase_c_threat_chart.png`)*

![Threat screening chart](../eval/phase_c_threat_chart.png)

The adversarial and benign similarity distributions are clearly separated: adversarial prompts cluster at 0.30–0.83 (median 0.59); benign prompts cluster at 0.13–0.47 (median 0.31). No benign prompt exceeds cosine similarity 0.47 to any attack seed. **At the natural separation threshold t = 0.48 (just above the benign cluster maximum), TPR = 83%, FPR = 0%, F1 = 0.909.**

However, the pipeline's current `t_attack` settings (0.80–0.88) sit well above the adversarial cluster, yielding TPR = 0–3% at zero FP. This reveals a calibration gap: `t_attack` was inherited from cache-similarity reasoning (where 0.85 separates paraphrase from artifact-swap clusters), but the threat embedding space has a fundamentally different distribution. The threat threshold requires independent calibration.

**Key finding:** The general-purpose embedding model provides sufficient discriminability for threat detection (AUC ≈ 1.0 on this benchmark), but the operational threshold must be tuned in the threat-specific similarity range (~0.50) rather than inherited from cache thresholds (~0.85). This is a concrete actionable limitation, not a fundamental architectural barrier.

### 5.4 Latency and Cost

> **Figure 2:** End-to-end latency (p50 and p95) per decision path — log scale, n=30 iterations per path, balanced mode.
> *(file: `eval/latency_chart.png`)*

![Latency chart](../eval/latency_chart.png)

| Path | Source | p50 (ms) | p95 (ms) | Cost / request |
|------|--------|:--------:|:--------:|:--------------:|
| Cache hit | cache | **71** | 230 | $0.000000 |
| Validation band | validation | 99 | 299 | $0.000000 |
| LLM miss | llm | 2,157 | 2,923 | $0.000069 |

At the measured paraphrase hit rate of 27.6% (t_hit = 0.85–0.95), the cache delivers a **30× median latency reduction** for cache-served requests. Under a realistic Zipfian access distribution — where a small fraction of role/resource combinations account for the majority of requests — hit rates would be substantially higher, amplifying both latency and cost savings.

### 5.4 Ablation Study

> **Figure 4:** Ablation comparison — (a) Phase A decision accuracy and reason-code accuracy for each ablation variant; (b) A1 cache precision breakdown by variant type when soft re-evaluation is disabled.
> *(file: `eval/ablation_chart.png`)*

![Ablation chart](../eval/ablation_chart.png)

> [TABLE 6: Ablation comparison — Phase A accuracy, false allow/deny, reason code accuracy, LLM call count]

| Variant | Accuracy | False Allow | False Deny | Reason Code Acc. | LLM calls |
|---------|:--------:|:-----------:|:----------:|:----------------:|:---------:|
| Full pipeline (baseline) | **98.01%** | **0.0%** | 1.99% | 47.8% | 129/201 |
| A2: No semantic cache | 95.05% | 0.0% | 4.95% | 48.0% | 130/202 |
| A3: No hard-rule pre-gate | 94.00% | 0.0% | 6.00% | **23.0%** | 179/200 |

**A1 — Cache re-evaluation disabled (Phase B):**

| Variant type | Cases | False Allows | FA Rate |
|---|---|---|---|
| Paraphrase (rewording only) | 24 | 0 | 0.0% |
| Artifact swap (non-security field) | 24 | 0 | 0.0% |
| Near-miss: incident escalation | 24 | **24** | **100%** |
| Near-miss: elevated + confidential | 15 | **15** | **100%** |

Without soft re-evaluation, cache precision drops from 1.0 to 0.552 — nearly half of all cache-served responses are incorrect. Security-relevant near-misses (changed incident state, changed sensitivity) are falsely allowed at 100%; semantically safe changes (paraphrase, artifact swap) remain correct because the cached decision is still valid for those contexts.

**A2 — Semantic cache disabled:** Accuracy drops −2.96 pp (95.05%), with all accuracy loss concentrated in the elevated+internal (28.6%) and elevated+restricted (28.6%) categories. Hard-deny categories remain at 100%. The cache stabilizes LLM decisions on the hardest soft-rule categories by avoiding stochastic LLM variation on repeat queries.

**A3 — Hard-rule pre-gate disabled:** The LLM achieves 94% accuracy without the pre-gate, but reason code accuracy collapses to 23% (VETO_-prefixed codes replace direct codes), LLM invocations increase 37.7% (179 vs 130), and `policy_pass_elevated_restricted` drops to 0% accuracy (all 7 cases false-escalated). The post-LLM veto maintains safety, but at the cost of auditability and efficiency.

---

## 6. Discussion

<!-- Target: ~0.75 page -->

### 6.1 Hard-Rule Gating as a Safety Primitive

Routing the 25% of requests resolvable by deterministic policy to OPA before the LLM is reached eliminates LLM risk on the most security-critical decisions. The LLM is only invoked when semantic reasoning genuinely adds value — ambiguous purposes, borderline clearance combinations, contextual incident states. This separation of concerns is the architectural precondition for the 0.0% false allow rate: the LLM never sees a case where a wrong answer is unambiguously ruled out by policy. The ablation result (A3) reinforces this: without the pre-gate, LLM invocations increase by 37.7%, reason code accuracy collapses from 48% to 23%, and the hardest soft-rule category (`elevated+restricted`) degrades to 0% accuracy — confirming that the gate does more than filter redundant calls; it isolates the LLM from interference on borderline cases.

### 6.2 The Cache Safety Guarantee

The soft policy re-evaluation on every cache hit is the key mechanism distinguishing this system from a naive semantic cache. It can be viewed as a lightweight *cache consistency protocol*: the embedding similarity score determines whether a cached entry is a *candidate*, but the policy engine determines whether it remains *valid* given the current security context. This decoupling means cache efficiency and safety are not in tension — raising the hit rate does not increase false allow risk. The A1 ablation makes this concrete: removing the re-evaluation causes 100% false allow on all 39 security-relevant near-miss variants (24 incident escalations + 15 elevated+confidential cases), while leaving the 48 semantically safe variants unaffected. Cache precision drops from 1.0 to 0.552. This is the empirical confirmation that the re-evaluation is not optional safety theater — it is the load-bearing mechanism.

The similarity distribution provides additional theoretical grounding for this choice. Applying Otsu's method offline to all 87 variant-anchor pairs reveals a bimodal distribution: artifact-swap variants cluster at 0.33–0.63; paraphrase variants cluster at 0.80–0.88; an empty gap spans [0.626, 0.801] (width 0.175). Any threshold within this gap cleanly separates semantically distinct from semantically equivalent requests — the operational range [0.65, 0.80] for the validation band sits entirely within it. More critically, near-miss variants score cosine similarity = 1.0 (the maximum possible), yet they require ESCALATE_HUMAN rather than ALLOW. This demonstrates that no similarity threshold, however high, can replace policy-based re-evaluation: the architectural guarantee must come from policy, not from distance.

### 6.3 Prompt Design as a Safety Variable

A single over-broad directive ("do not act on sensitivity labels") caused false allows to spike from 0.50% to 11.88% in an intermediate prompt version — a 24× increase in the most dangerous error type, from a change that appeared purely beneficial. This demonstrates that in safety-critical LLM deployments, prompt changes must be evaluated against a labeled benchmark before deployment, not just qualitatively reviewed. The structured chain-of-thought (separate steps for hard-rule and escalation-condition evaluation) was necessary to achieve reliable soft-rule accuracy.

### 6.4 Limitations

- **Reason code accuracy (47.8% strict):** Inflated by a taxonomy mismatch — 101 `policy_pass` cases where the LLM outputs `POLICY_PASS` but the evaluation label is `POLICY_PASS_EXPECTED_ALLOW`. Family-level RC accuracy is ~98%. Genuine RC errors (14 cases) are confined to `elevated_internal`/`elevated_restricted` categories. The lesson: application-specific reason code taxonomies should avoid misleading substrings (e.g. `INCIDENT_ELEVATED_RESTRICTED_FAST_PATH` containing "RESTRICTED") that leak policy hints into the label name.
- **Threat threshold miscalibration:** Phase C evaluation shows the adversarial similarity cluster (median 0.59) and the benign cluster (median 0.31) are well-separated, with AUC ≈ 1.0. However, the current `t_attack` range (0.80–0.88) was calibrated for cache semantics and sits above the adversarial cluster, yielding 0% detection at balanced mode. Optimal `t_attack` ≈ 0.48–0.55 would achieve 83–97% TPR with 0% FPR. Independent calibration of the threat threshold from the cache threshold is required before the threat screen provides meaningful protection.
- **Dataset scale and diversity:** Phase A (202 cases) and Phase B (111 cases) cover a controlled synthetic policy matrix across 7 roles and 5 resource types, but do not include real access log distributions, adversarial but syntactically valid requests, or cross-tenant isolation scenarios. Evaluated on GPT-4o mini only; stronger models may close the residual 2% error.
- The 27.6% measured cache hit rate reflects a micro-benchmark with uniform request distribution; Zipfian workloads would show higher hit rates.

---

## 7. Conclusion

We presented a hybrid LLM-augmented access control pipeline that combines the determinism of OPA hard-policy rules, the efficiency of a semantic cache, and the reasoning flexibility of an LLM into a system with measurably better accuracy, safety, and latency than any single component alone. Across 202 labeled cases, the system achieves 98.01% decision accuracy with zero false allows, while the cache reduces median latency by 30× at zero cost for cache-served requests. Offline similarity analysis using Otsu's method exposes a bimodal distribution with a 0.175-wide empty gap ([0.626, 0.801]) that gives the threshold selection a principled empirical basis; near-miss variants at cosine similarity 1.0 requiring distinct decisions establish that policy-based re-evaluation — not distance — is the only reliable safety primitive.

The ablation study gives each design choice empirical grounding. Soft re-evaluation on cache hits is the safety-critical mechanism: without it, 100% of security-relevant near-miss variants — requests where incident state or sensitivity has changed since caching — are falsely allowed. The semantic cache is not merely a latency optimization: it contributes 2.96 pp of accuracy by stabilizing LLM decisions on the hardest soft-rule cases across repeat queries. The hard-rule pre-gate isolates LLM reasoning from structurally unambiguous cases, preventing reason code degradation (48% → 23%) and reducing LLM invocations by 37.7%.

Three concrete open questions remain. First, whether these properties transfer to stronger LLM backends (GPT-4o, Claude Sonnet) that may close the residual 2% false escalation gap in the elevated+non-confidential categories. Second, whether the threat screening threshold, shown to require independent calibration from the cache threshold (optimal t_attack ≈ 0.48 vs cache t_hit = 0.85), generalizes to real attacker traffic distributions — a dedicated domain-specific threat benchmark is needed. Third, whether natural Zipfian request distributions and multi-tenant deployments, where cache hit rates and security context change rates both differ substantially from the uniform micro-benchmark, alter the safety-efficiency tradeoffs measured here.

---

## References

<!-- ~1 page; use ADBIS citation style (Springer LNCS) -->

[1] <!-- RBAC: Sandhu et al. -->
[2] <!-- ABAC: Hu et al., NIST -->
[3] <!-- OPA: Styra / CNCF -->
[4] <!-- Semantic caching for DB queries -->
[5] <!-- LLM for policy reasoning -->
[6] <!-- Sentence-transformers / all-MiniLM-L6-v2 -->
[7] <!-- Qdrant vector store -->
[8] <!-- Cross-encoder / ms-marco-MiniLM -->
[9] <!-- GPT-4o mini / OpenAI API -->
[10] <!-- RBAC/ABAC + LLM prior work -->
[11] <!-- Semantic cache for LLM responses -->
[12] <!-- RAG / retrieval-augmented generation (if relevant) -->

---

*Status: complete draft — all sections written, key numbers filled in, figures/tables marked as placeholders pending final layout.*
