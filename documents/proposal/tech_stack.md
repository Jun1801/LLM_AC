# Adaptive Tech Stack for LLM Access Control

## 1) Architecture Principles
- `Fail closed` for sensitive paths when uncertainty or outages occur.
- Keep control logic deterministic around LLM outputs.
- Separate online decision path from asynchronous learning path.
- Optimize for low-latency cache-first routing.

## 2) Recommended Stack by Layer
| Layer | Primary Choice | Why | Alternative |
|---|---|---|---|
| API gateway | FastAPI (Python) | Async IO, tight ML integration | Go gateway for extreme throughput |
| Policy engine (hard/soft) | OPA (Rego) or Cedar service | Deterministic, testable policy-as-code | In-app rule engine for MVP |
| Embeddings | SentenceTransformers (`bge-small`/`MiniLM`) | Fast inference, mature ecosystem | E5 small variants |
| Validation model | Cross-encoder MiniLM | Better semantic precision on uncertain matches | Lightweight reranker models |
| Vector DB | Qdrant | Strong filtering + Python DX | Milvus for large-scale clusters |
| Ticket/state store | Redis | TTL-native, low latency | KeyDB/Valkey |
| LLM serving | vLLM | High-throughput inference and KV efficiency | TGI or managed endpoint |
| Event bus | Kafka | Durable async pipelines | RabbitMQ for simpler ops |
| Observability | OpenTelemetry + Prometheus + Grafana | Unified traces, metrics, alerting | Datadog/New Relic |
| Audit store | Object store + query engine (S3/MinIO + Iceberg/Parquet) | Cheap immutable history | OLAP warehouse |

## 3) Model Strategy
### Online Models
- Bi-encoder for retrieval speed.
- Cross-encoder for ambiguous cache band.
- Mid-sized instruction model for arbitration (`7B-14B` equivalent).

### Offline/Periodic Tasks
- Attack-pattern clustering and blacklist refresh.
- Threshold calibration from false-allow/false-deny trends.
- Replay testing against policy and model version changes.

## 4) Environment Profiles (Adaptive by Maturity)
| Profile | Intended Scale | Infra Shape | Notes |
|---|---|---|---|
| MVP | <= 50 RPS | Single region, small GPU pool, managed Redis/Qdrant | Fastest path to measurable value |
| Growth | 50-300 RPS | Multi-AZ, autoscaled API + model services | Add policy service isolation |
| Enterprise | 300+ RPS | Multi-region active/active, queue buffering, dedicated inference clusters | Strong DR and compliance posture |

## 5) Security Controls in Stack
- mTLS between microservices.
- Signed service-to-service identity (SPIFFE/SPIRE or cloud equivalent).
- Secrets via dedicated manager (Vault / cloud KMS-backed store).
- Encrypt data at rest for vector/audit stores.
- WAF + rate limiting at gateway.
- Immutable policy and model version metadata on each decision.

## 6) Performance Targets and Tuning
- ANN index params tuned per mode (performance vs. recall).
- Batch embeddings where possible; keep per-request fallback path.
- Use ONNX/TensorRT for embedding and cross-encoder acceleration.
- Warm model instances for arbitration to avoid cold starts.
- Keep Redis and Vector DB in same region/AZ affinity as gateway.

## 7) Deployment Blueprint
1. `gateway-service`: request normalization, auth parsing, routing.
2. `policy-service`: hard/soft rule evaluation and veto checks.
3. `semantic-service`: embeddings + vector search + validation.
4. `decision-service`: LLM arbitration and structured output checks.
5. `cache-update-worker`: async TTL computation and vector upserts.
6. `audit-worker`: event enrichment, immutable write, monitoring hooks.

## 8) CI/CD and Quality Gates
- Unit tests for policy rules and routing logic.
- Regression suite with replayed historical decisions.
- Canary deployment with mirrored traffic.
- Automatic rollback on thresholded SLO breaches.
- Contract tests for request/response schema compatibility.

## 9) Cost Optimization Levers
- Raise cache-hit rate through better intent normalization.
- Restrict cross-encoder to uncertainty band only.
- Use model tiering by resource sensitivity.
- Schedule aggressive TTL for volatile domains to reduce bad reuse.
- Separate GPU pools for online arbitration vs. offline retraining.

## 10) Suggested First Implementation Order
1. Build deterministic hard-rule and audit pipeline first.
2. Add semantic cache with strict metadata filters.
3. Introduce cross-encoder validation band.
4. Add LLM arbitration with deterministic veto.
5. Enable adaptive modes and automated threshold tuning.
