.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

.\.venv\Scripts\python.exe scripts\benchmark_latency.py --iterations 30 --base-url http://127.0.0.1:8080 --json-out benchmark_results_4.json --csv-out benchmark_results_4.csv

.\.venv\Scripts\python.exe scripts\generate_cache_benchmark.py 
.\.venv\Scripts\python.exe scripts/evaluate_cache_benchmark.py --t-hit 0.90 --tag t90
.\.venv\Scripts\python.exe scripts/evaluate_synthetic_cases.py --tag prompt_v4
.\.venv\Scripts\python.exe scripts/run_ablation_study.py --base-url http://127.0.0.1:8080
  # Delete the cache collection
  curl -X DELETE http://localhost:6333/collections/acl_semantic_cache_v2

  # Recreate it with the same vector params (size=384, Cosine distance)
  curl -X PUT http://localhost:6333/collections/acl_semantic_cache_v2 \
    -H "Content-Type: application/json" \
    -d "{\"vectors\": {\"size\": 384, \"distance\": \"Cosine\"}}"
{
  "request_id": "emergency-seed-001",
  "timestamp_utc": "2026-04-14T03:10:00Z",
  "user": {
    "user_id": "user-emergency-001",
    "role": "manager",
    "department": "operations",
    "region": "us",
    "clearance_level": 3
  },
  "context": {
    "ip_address": "10.20.30.40",
    "device_id": "device-emergency-001",
    "session_id": "sess-emergency-001",
    "mfa_state": "passed",
    "incident_state": "normal"
  },
  "resource": {
    "resource_type": "document",
    "resource_id": "document-emergency-001",
    "sensitivity": "internal"
  },
  "query": {
    "prompt": "Urgent need access to quarterly finance report for production incident response alpha-77",
    "purpose": "incident response"
  }
}
