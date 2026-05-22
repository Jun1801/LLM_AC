# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

LLM Semantic Access Control MVP — a FastAPI modular-monolith that evaluates access requests against hard policy rules (OPA/Rego) and semantic/LLM-based reasoning, with embedding-powered caching.

## Environment Setup

Use `uv` (not `pip`) for all dependency management:

```bash
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[test,llm,ops]"
cp .env.example .env                   # fill in secrets before first run
```

Always verify the active interpreter points inside `.venv/` (`which python`), never system Python.

## Common Commands

```bash
# Run the server
uvicorn app.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_pipeline.py

# Run a single test
pytest tests/test_pipeline.py::test_name

# Benchmark latency
python eval/benchmark_latency.py --iterations 30 --base-url http://127.0.0.1:8080

# Start local infrastructure (OPA, Redis, Qdrant)
docker compose up -d
```

## Architecture

### Access Decision Pipeline (`app/pipeline.py`)

Requests flow through these stages in order:

1. **Ingestion** (`app/ingestion.py`) — normalize `AccessRequest`
2. **Mode check** (`app/mode_manager.py`) — performance / balanced / conservative thresholds
3. **Hard policy** (`app/clients/policy_client.py`) — OPA evaluates `policies/hard.rego` (clearance, role, MFA)
4. **Threat screening** (`app/threat_screen.py`) — vector-DB lookup for known attack patterns
5. **Cache lookup** (`app/cache_lookup.py`) — embedding similarity search in Qdrant
6. **Validation** (`app/validation.py`) — cross-encoder confidence scoring
7. **LLM decision** (`app/clients/llm_client.py`) — OpenAI or vLLM when cache/validation is insufficient
8. **Response** — `AccessResponse` with decision, source, rationale, and perf metrics

### Key Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app, route registration |
| `app/pipeline.py` | Core pipeline orchestration |
| `app/models.py` | Pydantic schemas (`AccessRequest`, `AccessResponse`, `Decision`, `Mode`, `Sensitivity`) |
| `app/dependencies.py` | `@lru_cache` singletons; `build_pipeline()` wires everything |
| `app/config.py` | `Settings` via pydantic-settings; env vars with `__` delimiter for nested config |
| `policies/hard.rego` | OPA hard rules (clearance level, role-resource mapping, MFA requirements) |
| `tests/conftest.py` | Pytest fixtures (`sample_request`, `reset_singletons`) |

### Dependency Injection

All services are `@lru_cache` singletons instantiated in `app/dependencies.py`. Use `reset_singletons` fixture in tests to clear them between test runs.

### Decision Sources

`AccessResponse.source` tells you where the decision came from: `hard_rule`, `cache`, `validation`, or `llm`.

### Optional Infrastructure

External services (Qdrant, Redis, Kafka) are opt-in via `*_ENABLED` env vars. When disabled, the corresponding pipeline stage is skipped gracefully.

## Configuration

Key `.env` variables:

```
OPA_URL / OPA_ENABLED
OPENAI_API_KEY / OPENAI_MODEL   # or VLLM_BASE_URL for local LLM
EMBEDDING_MODEL_ID              # default: sentence-transformers/all-MiniLM-L6-v2
VALIDATION_MODEL_ID             # default: cross-encoder/ms-marco-MiniLM-L-6-v2
VALIDATION_THRESHOLD            # default: 0.80
QDRANT_URL / QDRANT_ENABLED
REDIS_URL / REDIS_ENABLED
KAFKA_BOOTSTRAP_SERVERS / KAFKA_ENABLED
MODEL_DEVICE                    # cpu or cuda
MODEL_CACHE_DIR / MODEL_LOCAL_FILES_ONLY
```

Use `__` delimiter for nested settings (e.g. `LLM__MODEL=qwen3.5-9b`).

## Workflow Rules (from AGENTS.md)

- Enter plan mode for any non-trivial task (3+ steps or architectural decisions).
- Track progress in `tasks/todo.md`; capture lessons in `tasks/lessons.md` after corrections.
- Never mark a task done without proving it works (run tests, check logs).
- For large or scattered file edits, apply the **Shadow File Technique** (see `.claude/rules/shadow_file.md`): write a `.shadow` file from scratch, verify, then replace the original.
