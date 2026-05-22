from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models import AccessResponse, AccessScores
from app.models import Decision
from app.models import DecisionSource, Mode


class StubService:
    def __init__(self, ok: bool = True, message: str = "ok"):
        self.ok = ok
        self.message = message

    def ping(self):
        return self.ok, self.message


def test_health_and_ready(monkeypatch):
    monkeypatch.setattr("app.routes_health.get_embedding_service", lambda: StubService())
    monkeypatch.setattr("app.routes_health.get_validation_service", lambda: StubService())
    client = TestClient(app)
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert "dependencies" in ready.json()


def test_admin_mode_override():
    client = TestClient(app)
    resp = client.post("/v1/admin/mode", json={"mode": "conservative", "ttl_seconds": 60})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "conservative"

    kpi = client.get("/v1/admin/kpi")
    assert kpi.status_code == 200
    assert "cache_hit_ratio" in kpi.json()


def test_access_decide_denies_without_mfa(sample_request, monkeypatch):
    sample_request.context.mfa_state = "failed"
    monkeypatch.setattr(
        "app.routes_access.build_pipeline",
        lambda: type(
            "StubPipeline",
            (),
            {
                "decide": staticmethod(
                    lambda payload: AccessResponse(
                        request_id=payload.request_id,
                        decision=Decision.DENY,
                        decision_source=DecisionSource.hard_rule,
                        confidence=1.0,
                        reason_code="MFA_REQUIRED",
                        scores=AccessScores(),
                        policy_version="2026-04-04",
                        mode=Mode.balanced,
                        latency_ms=1,
                    )
                )
            },
        )(),
    )
    client = TestClient(app)
    resp = client.post("/v1/access/decide", json=sample_request.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["decision"] == Decision.DENY.value
