from __future__ import annotations

from fastapi import FastAPI

from app.observability import setup_observability
from app.routes_access import router as access_router
from app.routes_admin import router as admin_router
from app.routes_health import router as health_router

app = FastAPI(title="LLM Semantic ACL", version="0.1.0")
setup_observability(app)
app.include_router(health_router)
app.include_router(access_router)
app.include_router(admin_router)
