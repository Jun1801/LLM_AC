from __future__ import annotations

from typing import Any


def build_grounding_facts(structured_facts: dict[str, Any]) -> list[str]:
    user = structured_facts.get("user", {}) or {}
    resource = structured_facts.get("resource", {}) or {}
    context = structured_facts.get("context", {}) or {}
    query = structured_facts.get("query", {}) or {}
    facts = [
        f"role={user.get('role', '')}",
        f"department={user.get('department', '')}",
        f"region={user.get('region', '')}",
        f"clearance_level={user.get('clearance_level', '')}",
        f"resource_type={resource.get('resource_type', '')}",
        f"sensitivity={resource.get('sensitivity', '')}",
        f"incident_state={context.get('incident_state', '')}",
        f"mfa_state={context.get('mfa_state', '')}",
        f"session_present={bool(context.get('session_id'))}".lower(),
        f"purpose={query.get('purpose', '')}",
    ]
    return [fact for fact in facts if not fact.endswith("=")]


def grounded_facts_only(candidate_facts: list[str] | None, allowed_facts: list[str]) -> list[str]:
    if not candidate_facts:
        return []
    allowed = set(allowed_facts)
    grounded: list[str] = []
    for fact in candidate_facts:
        if isinstance(fact, str) and fact in allowed and fact not in grounded:
            grounded.append(fact)
    return grounded
