from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient

from apps.api.main import app
from packages.core.observability.logging import (
    JsonLogFormatter,
    bind_observability_context,
    clear_observability_context,
)
from packages.core.observability.telemetry import REQUIRED_LOG_FIELDS


def test_json_log_formatter_emits_required_fields_with_null_defaults() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("test.cutagent.json")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    bind_observability_context(request_id="req_test", run_id="run_1")
    try:
        logger.info("structured message")
    finally:
        clear_observability_context()

    record = json.loads(stream.getvalue())

    assert record["message"] == "structured message"
    assert record["request_id"] == "req_test"
    assert record["run_id"] == "run_1"
    for field in REQUIRED_LOG_FIELDS:
        assert field in record
    assert record["trace_id"] is None
    assert record["user_id"] is None


def test_api_access_log_contains_request_context_and_timing() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("cutagent.api")
    old_handlers = logger.handlers[:]
    old_propagate = logger.propagate
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        with TestClient(app) as client:
            response = client.get("/api/health", headers={"X-Request-Id": "req_access"})
    finally:
        logger.handlers = old_handlers
        logger.propagate = old_propagate

    assert response.status_code == 200
    entries = [json.loads(line) for line in stream.getvalue().splitlines() if line]
    access = [entry for entry in entries if entry.get("event") == "api_request"]

    assert access
    assert access[-1]["request_id"] == "req_access"
    assert access[-1]["method"] == "GET"
    assert access[-1]["route"] == "/api/health"
    assert access[-1]["status"] == 200
    assert isinstance(access[-1]["duration_ms"], float)
