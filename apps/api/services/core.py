from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.common import (
    repository,
    request_id,
)
from packages.core import contracts as c
from packages.core.config import validate_startup_settings
from packages.core.observability import metric_snapshot

def health(request: Request) -> c.OkResponse:

    return c.OkResponse(request_id=request_id())


def readiness(request: Request) -> JSONResponse:
    """Operational readiness probe (not part of the OpenAPI contract).

    In production this surfaces any unsafe-config preflight findings as a 503 so
    an orchestrator never routes traffic to a misconfigured replica. Outside
    production the preflight is a no-op, so this reflects a plain liveness-ish
    ready. PR4 (#67) extends this with live Redis/dependency checks.
    """
    settings = request.app.state.settings
    issues = validate_startup_settings(settings)
    payload = {
        "status": "ready" if not issues else "not_ready",
        "environment": settings.deployment.environment,
        "preflight_issues": issues,
        "request_id": request_id(),
    }
    return JSONResponse(status_code=200 if not issues else 503, content=payload)


def metrics(request: Request) -> str:

    return metric_snapshot(repository(request))


def network_diagnostics(request: Request) -> JSONResponse:
    """Per-dependency segment health for the Web→VPS→Mac→OSS topology (issue #77).

    Live-probes the cheap dependencies (Postgres, Redis) with per-hop latency and
    echoes the configured OSS / Temporal endpoints. Operational only — not part of
    the OpenAPI contract. (OSS/Temporal live latency + Server-Timing is a
    follow-up.)
    """
    settings = request.app.state.settings
    hops: dict[str, dict] = {}

    session_factory = getattr(request.app.state, "sqlalchemy_session_factory", None)
    if session_factory is not None:
        started = time.monotonic()
        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
            hops["postgres"] = {
                "status": "ok",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }
        except Exception as exc:  # noqa: BLE001 — diagnostics must not raise.
            hops["postgres"] = {"status": "failed", "error": str(exc)}
    else:
        hops["postgres"] = {"status": "not_configured"}

    if settings.redis_url:
        started = time.monotonic()
        try:
            import redis

            client = redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=0.5, socket_timeout=1.0
            )
            client.ping()
            hops["redis"] = {
                "status": "ok",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }
        except Exception as exc:  # noqa: BLE001
            hops["redis"] = {"status": "failed", "error": str(exc)}
    else:
        hops["redis"] = {"status": "not_configured"}

    hops["oss"] = {
        "status": "configured",
        "backend": settings.object_store.backend,
        "endpoint": settings.object_store.s3.endpoint_url
        if settings.object_store.backend == "s3"
        else settings.object_store.local_path,
    }
    hops["temporal"] = {
        "status": "configured",
        "runtime": settings.workflow.runtime,
        "address": settings.workflow.temporal_address,
    }

    overall = "degraded" if any(h.get("status") == "failed" for h in hops.values()) else "ok"
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={"status": overall, "hops": hops, "request_id": request_id()},
    )
