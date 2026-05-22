# Tech Stack References (from `tech_stack.md` + `get-api-docs` skill)

## Source Inputs
- [tech_stack.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/tech_stack.md)
- [SKILL.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/.agents/skills/get-api-docs/SKILL.md)

## Fetch Method Used
Commands used per skill:
- `chub search "<library>" --json`
- `chub get <id> --lang py|js -o <file>`

All fetched docs were saved under `plans/.refs/`.

## Core Stack References
| Tech Stack Area | Chub Doc ID | Lang | Version (from doc metadata) | Updated On | Local Copy |
|---|---|---|---|---|---|
| API Gateway / Service API | `fastapi/package` | `python` | `0.135.1` | `2026-03-11` | [fastapi_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/fastapi_package.md) |
| Embeddings + Cross-Encoder | `sentence-transformers/package` | `python` | `5.2.3` | `2026-03-12` | [sentence_transformers_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/sentence_transformers_package.md) |
| Vector DB Client | `qdrant-client/package` | `python` | `1.17.0` | `2026-03-12` | [qdrant_client_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/qdrant_client_package.md) |
| TTL / State Store | `redis/package` | `python` | `7.3.0` | `2026-03-12` | [redis_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/redis_package.md) |
| LLM Serving | `vllm/package` | `python` | `0.17.1` | `2026-03-11` | [vllm_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/vllm_package.md) |
| Event Bus (Kafka) | `confluent-kafka/package` | `python` | `2.13.2` | `2026-03-12` | [confluent_kafka_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/confluent_kafka_package.md) |
| Observability SDK | `opentelemetry/sdk` | `python` | `1.40.0` | `2026-03-12` | [opentelemetry_sdk.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_sdk.md) |
| FastAPI Tracing | `opentelemetry/instrumentation-fastapi` | `python` | `0.61b0` | `2026-03-12` | [opentelemetry_instrumentation_fastapi.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_instrumentation_fastapi.md) |
| Metrics Export | `prometheus-client/package` | `python` | `0.24.1` | `2026-03-12` | [prometheus_client_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/prometheus_client_package.md) |
| OTel->Prometheus Exporter | `opentelemetry/exporter-prometheus` | `python` | `0.61b0` | `2026-03-12` | [opentelemetry_exporter_prometheus.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_exporter_prometheus.md) |

## Alternative / Optional References
| Area | Chub Doc ID | Lang | Version | Local Copy | Note |
|---|---|---|---|---|---|
| Event Bus Alternative (RabbitMQ) | `rabbitmq/message-queue` | `python` | `1.3.2` | [rabbitmq_message_queue.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/rabbitmq_message_queue.md) | Alternative to Kafka path |
| Cedar-based managed auth option | `aws/verifiedpermissions` | `javascript` | `3.1007.0` | [aws_verifiedpermissions.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/aws_verifiedpermissions.md) | Useful when adopting Cedar via AWS Verified Permissions |

## Gaps Found in Chub Search
No direct/clean chub doc match was found for:
- OPA/Rego (exact runtime docs)
- Grafana (core docs)
- Milvus
- MinIO
- Apache Iceberg
- SPIFFE/SPIRE

If needed, we can keep these in `tech_stack.md` as valid choices, but mark them as "manual-source required" until equivalent chub docs are available.

## Implementation Notes Derived from Fetched Docs
- FastAPI and most Python packages in this stack now assume Python `>=3.10`.
- `sentence-transformers` supports both embedding and cross-encoder patterns in one package, matching your Phase C/Phase D design.
- `qdrant-client` supports in-memory/local mode for MVP testing and remote/cloud mode for production.
- `redis` current doc set points to `redis.readthedocs.io` as canonical docs root.
- `vllm` docs emphasize backend-specific install paths; default wheel assumptions should not be hard-coded.
- OpenTelemetry package versions are split (`sdk` 1.x, contrib exporters/instrumentations 0.xx beta line), so version pinning should be explicit.

## Raw Reference Files (Fetched)
- [fastapi_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/fastapi_package.md)
- [sentence_transformers_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/sentence_transformers_package.md)
- [qdrant_client_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/qdrant_client_package.md)
- [redis_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/redis_package.md)
- [vllm_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/vllm_package.md)
- [confluent_kafka_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/confluent_kafka_package.md)
- [opentelemetry_sdk.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_sdk.md)
- [opentelemetry_instrumentation_fastapi.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_instrumentation_fastapi.md)
- [prometheus_client_package.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/prometheus_client_package.md)
- [opentelemetry_exporter_prometheus.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/opentelemetry_exporter_prometheus.md)
- [rabbitmq_message_queue.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/rabbitmq_message_queue.md)
- [aws_verifiedpermissions.md](/d:/Study%20Documents/Other%20subjects/LLM_AC/plans/.refs/aws_verifiedpermissions.md)
