from __future__ import annotations

from app.models import AccessRequest


class IngestionService:
    def normalize(self, req: AccessRequest) -> AccessRequest:
        req.query.prompt = " ".join(req.query.prompt.split())
        req.query.purpose = req.query.purpose.strip()
        req.user.role = req.user.role.strip().lower()
        req.user.department = req.user.department.strip().lower()
        req.user.region = req.user.region.strip().lower()
        return req

