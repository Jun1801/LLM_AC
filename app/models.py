from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IncidentState(str, Enum):
    normal = "normal"
    elevated = "elevated"
    critical = "critical"


class Sensitivity(str, Enum):
    public = "public"
    internal = "internal"
    restricted = "restricted"
    confidential = "confidential"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    ALLOW_CACHE = "ALLOW_CACHE"
    ALLOW_EMERGENCY = "ALLOW_EMERGENCY"


class DecisionSource(str, Enum):
    hard_rule = "hard_rule"
    threat_gate = "threat_gate"
    cache = "cache"
    validation = "validation"
    llm = "llm"


class Mode(str, Enum):
    loose = "loose"
    moderate = "moderate"
    performance = "performance"
    balanced = "balanced"
    conservative = "conservative"
    strict = "strict"


class UserInfo(BaseModel):
    user_id: str
    role: str
    department: str
    region: str
    clearance_level: int


class ContextInfo(BaseModel):
    ip_address: str
    device_id: str
    session_id: str
    mfa_state: str
    incident_state: IncidentState = IncidentState.normal


class ResourceInfo(BaseModel):
    resource_type: str
    resource_id: str
    sensitivity: Sensitivity


class QueryInfo(BaseModel):
    prompt: str
    purpose: str


class AccessRequest(BaseModel):
    request_id: str
    timestamp_utc: datetime
    user: UserInfo
    context: ContextInfo
    resource: ResourceInfo
    query: QueryInfo


class AccessScores(BaseModel):
    threat_similarity: float | None = None
    cache_similarity: float | None = None
    cross_encoder_score: float | None = None


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRationale(BaseModel):
    summary: str | None = None
    facts: list[str] = Field(default_factory=list)


class AccessResponse(BaseModel):
    request_id: str
    decision: Decision
    decision_source: DecisionSource
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: str
    scores: AccessScores = Field(default_factory=AccessScores)
    policy_version: str
    mode: Mode
    latency_ms: int
    llm_usage: LLMUsage | None = None
    estimated_cost_usd: float = 0.0
    rationale: LLMRationale | None = None


class ModeOverrideRequest(BaseModel):
    mode: Mode
    ttl_seconds: int = Field(default=900, ge=1, le=86400)


class ModeOverrideResponse(BaseModel):
    mode: Mode
    expires_at_utc: datetime


class HealthResponse(BaseModel):
    status: str


class ReadyDependency(BaseModel):
    name: str
    ok: bool
    message: str = ""


class ReadyResponse(BaseModel):
    status: str
    dependencies: list[ReadyDependency]


class PolicyResult(BaseModel):
    allow: bool
    reason_code: str
    matched_rule: str | None = None


class ThreatResult(BaseModel):
    similarity: float
    matched_pattern_id: str | None = None


class CacheCandidate(BaseModel):
    hit: bool = False
    similarity: float = 0.0
    cached_text: str | None = None
    cached_decision: Decision | None = None
    policy_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    is_hit: bool
    score: float


class LLMDecisionProposal(BaseModel):
    proposed_decision: Decision
    confidence: float
    reason_code: str
    llm_usage: LLMUsage | None = None
    estimated_cost_usd: float = 0.0
    rationale: LLMRationale | None = None


class AuditEvent(BaseModel):
    request_id: str
    user_id: str
    resource_id: str
    decision: Decision
    decision_source: DecisionSource
    policy_version: str
    mode: Mode
    latency_ms: int
    scores: AccessScores


class CacheUpdateMessage(BaseModel):
    request: AccessRequest
    response: AccessResponse
    embedding: list[float]


class FeedbackEvent(BaseModel):
    request_id: str
    prompt: str
    decision: Decision
    reason_code: str
    suspicious: bool = False
