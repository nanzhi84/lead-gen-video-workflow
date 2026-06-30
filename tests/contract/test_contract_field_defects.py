"""Contract-layer defect guards.

Covers two latent defects flagged in the architecture report:

* ``OutboxEvent.dedupe_key`` was declared twice — the second declaration
  (``str | None = None``) shadowed/loosened the intended required ``str``.
  The outbox DB column is ``NOT NULL`` and every producer always supplies a
  ``dedupe_key``, so the field must be required.
* A general scan asserting no Pydantic model in ``packages/core/contracts``
  declares the same field name twice (which Python/ruff silently accept,
  letting the later annotation win).
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import ValidationError

import packages.core.contracts as contracts_pkg
from packages.core.contracts import LipSyncOptions, OutboxEvent

_CONTRACTS_DIR = pathlib.Path(contracts_pkg.__file__).parent
_CONTRACT_FILES = sorted(_CONTRACTS_DIR.glob("*.py"))

# Advanced LipSync request-layer fields removed in issue #115: they were exposed
# on the contract / OpenAPI / frontend but never wired into the digital_human_v2
# LipSync node's ProviderCall.input (only portrait_uri/audio_uri/duration_sec/
# timeout_minutes flow through), and ``query_face_threshold`` carried a unit
# mismatch (0..1 float on the contract vs the 120..200 int the videoretalk
# adapter expects). They must no longer be accepted on the user request layer.
_REMOVED_LIPSYNC_FIELDS = (
    "ref_image_artifact_id",
    "video_extension",
    "query_face_threshold",
)


def test_lipsync_options_drops_unwired_advanced_fields():
    for name in _REMOVED_LIPSYNC_FIELDS:
        assert name not in LipSyncOptions.model_fields, (
            f"{name} was removed from the LipSync request layer (#115) but is "
            "still declared on LipSyncOptions"
        )


@pytest.mark.parametrize("name", _REMOVED_LIPSYNC_FIELDS)
def test_lipsync_options_rejects_removed_field(name):
    # ContractModel is extra="forbid", so a stored/legacy request still carrying
    # one of these keys must now raise instead of silently round-tripping.
    with pytest.raises(ValidationError):
        LipSyncOptions.model_validate({name: None})


def test_lipsync_options_still_accepts_supported_fields():
    options = LipSyncOptions(enabled=True, timeout_minutes=45)
    assert options.enabled is True
    assert options.timeout_minutes == 45


def test_outbox_event_dedupe_key_is_required_str():
    field = OutboxEvent.model_fields["dedupe_key"]
    assert field.annotation is str, (
        f"dedupe_key must be a required str, got {field.annotation!r}"
    )
    assert field.is_required(), "dedupe_key must be required (no default)"


def test_outbox_event_rejects_missing_dedupe_key():
    with pytest.raises(ValidationError):
        OutboxEvent(
            id="evt_1",
            topic="workflow.run.updated",
            aggregate_type="run",
            aggregate_id="run_1",
            payload_schema="run.updated.v1",
            payload={},
        )


def test_outbox_event_accepts_dedupe_key():
    event = OutboxEvent(
        id="evt_1",
        topic="workflow.run.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        dedupe_key="run_1:running",
        payload_schema="run.updated.v1",
        payload={},
    )
    assert event.dedupe_key == "run_1:running"


def _duplicate_fields(path: pathlib.Path) -> list[str]:
    """Return human-readable descriptions of duplicate annotated fields."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: dict[str, int] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                if name in seen:
                    problems.append(
                        f"{path.name}:{node.name}.{name} "
                        f"redeclared at lines {seen[name]} and {stmt.lineno}"
                    )
                else:
                    seen[name] = stmt.lineno
    return problems


def test_no_contract_model_has_duplicate_field_declarations():
    assert _CONTRACT_FILES, "expected to find contract source files to scan"
    problems: list[str] = []
    for path in _CONTRACT_FILES:
        problems.extend(_duplicate_fields(path))
    assert not problems, "duplicate field declarations found:\n" + "\n".join(problems)
