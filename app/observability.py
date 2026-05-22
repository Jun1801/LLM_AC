from __future__ import annotations

from fastapi import FastAPI


def setup_observability(app: FastAPI) -> None:
    """Attach OpenTelemetry instrumentation when optional deps are available."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
    except Exception:  # noqa: BLE001
        return
    FastAPIInstrumentor.instrument_app(app, excluded_urls="^/health$,^/ready$")

