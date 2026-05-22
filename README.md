# Safety-Preserving Semantic Caching for LLM-Augmented Access Control

A FastAPI modular-monolith that evaluates access requests against hard policy rules (OPA/Rego) and LLM-based reasoning, with an embedding-powered semantic cache that guarantees zero false-allow rate through context re-evaluation on every cache hit.

## Quick Start

```bash
# Install dependencies (use uv, not pip)
uv venv && .venv\Scripts\activate      # Windows
uv pip install -e ".[test,llm,ops]"

# Configure environment
cp .env.example .env                   # fill in API keys and service URLs

# Start local infrastructure (OPA, Redis, Qdrant)
docker compose up -d

# Run the server
uvicorn app.main:app --reload
```

## Pipeline Stages

Requests flow through these stages in order:

1. **Ingestion** — normalize `AccessRequest` into canonical form
2. **Hard policy** (OPA/Rego) — deny on clearance violation, MFA failure, role mismatch
3. **Threat screening** — embedding similarity against known adversarial prompt seeds
4. **Cache lookup** — cosine similarity search in Qdrant; HIT/NEAR-HIT/MISS routing
5. **Context re-evaluation** — re-check dynamic security conditions on every cache hit
6. **Cross-encoder validation** — finer-grained scoring for NEAR-HIT requests
7. **LLM decision** — GPT-4o mini or vLLM for cache misses, with OPA post-veto
8. **Audit** — every decision written to immutable audit stream

## Repository Layout

```
app/            FastAPI app and domain modules
  pipeline.py   Core pipeline orchestration
  mode_manager.py  Threshold configuration (loose/balanced/strict)
  threat_screen.py Adversarial prompt screening
  cache_lookup.py  Qdrant embedding cache
workers/        Async audit and cache-update workers
policies/       OPA/Rego hard rules
scripts/        Benchmarking and evaluation scripts
eval/           Benchmark datasets and results (Phase A/B/C)
paper/          ADBIS 2026 short paper source
tests/          Unit and integration tests
```

## Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/access/decide` | Evaluate an access request |
| `POST` | `/v1/admin/mode` | Set pipeline mode (loose/balanced/strict/…) |
| `GET`  | `/health` | Liveness check |
| `GET`  | `/ready` | Readiness check |

## Configuration

Key `.env` variables:

```
OPENAI_API_KEY / OPENAI_MODEL
OPA_URL / OPA_ENABLED
QDRANT_URL / QDRANT_ENABLED
REDIS_URL / REDIS_ENABLED
EMBEDDING_MODEL_ID          # default: sentence-transformers/all-MiniLM-L6-v2
VALIDATION_MODEL_ID         # default: cross-encoder/ms-marco-MiniLM-L-6-v2
MODEL_DEVICE                # cpu or cuda
```

## Running Tests and Benchmarks

```bash
pytest                                                        # all tests
pytest tests/test_pipeline.py                                 # single file
python scripts/benchmark_latency.py --iterations 30           # latency benchmark
python scripts/evaluate_threat_screen.py                      # Phase C eval
```

## Threshold Modes

| Mode | T_hit | T_validate_low | T_attack |
|------|-------|----------------|----------|
| loose | 0.80 | 0.60 | 0.52 |
| moderate | 0.85 | 0.65 | 0.50 |
| balanced | 0.90 | 0.70 | 0.50 |
| strict | 0.95 | 0.80 | 0.48 |
