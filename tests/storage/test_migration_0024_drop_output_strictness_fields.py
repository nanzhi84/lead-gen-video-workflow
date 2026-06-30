"""Regression for migration 0024 (issue #118).

The un-consumed Output/Strictness request-layer fields
(``OutputOptions.{export_jianying_draft,export_editor_handoff,upload_to_oss,
keep_local_originals,format}`` and
``StrictnessOptions.{broll_insufficient_policy,bgm_unavailable_policy,
strict_cost_pricing}``) were dropped from the contract. ``digital_human_video``
jobs persisted these keys inside ``jobs.request->'output'`` /
``jobs.request->'strictness'`` (via ``model_dump`` with defaults), so under
``extra="forbid"`` re-reading a legacy row through
``DigitalHumanVideoRequest.model_validate`` (the path in
``packages/production/sqlalchemy_mappers.py``) would raise. Migration 0024 strips
the keys; this test proves a legacy row is broken before the upgrade and validates
cleanly afterwards, against real Postgres (the migration is PostgreSQL-only).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import text

from packages.core.contracts import (
    DigitalHumanVideoRequest,
    OutputOptions,
    StrictnessOptions,
    VoiceOptions,
)
from packages.core.storage.database import JobRow
from packages.core.storage.repository import new_id

MIGRATION_PATH = Path(
    "packages/core/storage/alembic/versions/0024_drop_output_strictness_fields.py"
)

_REMOVED_OUTPUT_KEYS = (
    "export_jianying_draft",
    "export_editor_handoff",
    "upload_to_oss",
    "keep_local_originals",
    "format",
)
_REMOVED_STRICTNESS_KEYS = (
    "broll_insufficient_policy",
    "bgm_unavailable_policy",
    "strict_cost_pricing",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig_0024", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chains_to_single_head():
    text_src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "0024_drop_out_strict_fields"' in text_src
    assert 'down_revision = "0023_drop_lipsync_adv_fields"' in text_src
    # alembic version_num column is VARCHAR(32); the id must fit.
    assert len("0024_drop_out_strict_fields") <= 32


def _legacy_request_with_dropped_fields() -> dict:
    """A digital_human_video request as persisted before #118: a full, otherwise
    valid request whose output/strictness blocks still carry the removed keys."""
    request = DigitalHumanVideoRequest(
        case_id="case_legacy",
        script="hi",
        voice=VoiceOptions(voice_id="voice_demo"),
        output=OutputOptions(width=1080, height=1920, fps=30),
        strictness=StrictnessOptions(
            strict_timestamps=True, portrait_insufficient_policy="hard_fail"
        ),
    ).model_dump(mode="json")
    request["output"]["export_jianying_draft"] = True
    request["output"]["export_editor_handoff"] = True
    request["output"]["upload_to_oss"] = True
    request["output"]["keep_local_originals"] = False
    request["output"]["format"] = "mp4"
    request["strictness"]["broll_insufficient_policy"] = "soft_degrade"
    request["strictness"]["bgm_unavailable_policy"] = "soft_degrade"
    request["strictness"]["strict_cost_pricing"] = False
    return request


def test_upgrade_strips_unconsumed_output_strictness_keys(db_session_factory):
    legacy_request = _legacy_request_with_dropped_fields()

    # Legacy rows are unreadable under the slimmed contract until migrated.
    with pytest.raises(ValidationError):
        DigitalHumanVideoRequest.model_validate(legacy_request)

    job_id = new_id("job")
    with db_session_factory() as session:
        session.add(
            JobRow(
                id=job_id,
                type="digital_human_video",
                status="succeeded",
                request_schema="DigitalHumanVideoRequest.v1",
                request=legacy_request,
            )
        )
        session.commit()

    engine = db_session_factory.kw["bind"]
    module = _load_migration()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()

    with engine.connect() as conn:
        stored = conn.execute(
            text("select request from jobs where id = :id"), {"id": job_id}
        ).scalar_one()

    output = stored["output"]
    strictness = stored["strictness"]
    for key in _REMOVED_OUTPUT_KEYS:
        assert key not in output
    for key in _REMOVED_STRICTNESS_KEYS:
        assert key not in strictness
    # Untouched supported fields survive.
    assert output["width"] == 1080
    assert output["height"] == 1920
    assert output["fps"] == 30
    assert strictness["strict_timestamps"] is True
    assert strictness["portrait_insufficient_policy"] == "hard_fail"
    # The migrated row now validates cleanly against the slimmed contract.
    DigitalHumanVideoRequest.model_validate(stored)


def test_upgrade_is_idempotent_and_skips_non_digital_human(db_session_factory):
    legacy_request = _legacy_request_with_dropped_fields()
    dh_id = new_id("job")
    other_id = new_id("job")
    other_request = {"schema_version": "publish_batch_request.v1", "marker": "keep"}

    with db_session_factory() as session:
        session.add(
            JobRow(
                id=dh_id,
                type="digital_human_video",
                status="succeeded",
                request_schema="DigitalHumanVideoRequest.v1",
                request=legacy_request,
            )
        )
        session.add(
            JobRow(
                id=other_id,
                type="publish_batch",
                status="succeeded",
                request_schema="PublishBatchRequest.v1",
                request=other_request,
            )
        )
        session.commit()

    engine = db_session_factory.kw["bind"]
    module = _load_migration()
    # Run twice: the second pass must be a no-op (keys already gone).
    for _ in range(2):
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                module.upgrade()

    with engine.connect() as conn:
        dh_request = conn.execute(
            text("select request from jobs where id = :id"), {"id": dh_id}
        ).scalar_one()
        kept_request = conn.execute(
            text("select request from jobs where id = :id"), {"id": other_id}
        ).scalar_one()

    for key in _REMOVED_OUTPUT_KEYS:
        assert key not in dh_request["output"]
    for key in _REMOVED_STRICTNESS_KEYS:
        assert key not in dh_request["strictness"]
    # Non digital_human_video rows are never touched.
    assert kept_request == other_request
