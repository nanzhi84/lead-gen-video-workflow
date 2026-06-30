"""Regression for migration 0023 (issue #115).

The advanced LipSync request-layer fields (``ref_image_artifact_id`` /
``video_extension`` / ``query_face_threshold``) were dropped from
``LipSyncOptions``. ``digital_human_video`` jobs persisted these keys inside
``jobs.request->'lipsync'`` (via ``model_dump`` with defaults), so under
``extra="forbid"`` re-reading a legacy row through
``DigitalHumanVideoRequest.model_validate`` (the path in
``packages/production/sqlalchemy_mappers.py``) would raise. Migration 0023 strips
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

from packages.core.contracts import DigitalHumanVideoRequest, VoiceOptions
from packages.core.storage.database import JobRow
from packages.core.storage.repository import new_id

MIGRATION_PATH = Path(
    "packages/core/storage/alembic/versions/0023_drop_lipsync_advanced_fields.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig_0023", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chains_to_single_head():
    text_src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "0023_drop_lipsync_adv_fields"' in text_src
    assert 'down_revision = "0022_drop_publish_hashtags"' in text_src
    # alembic version_num column is VARCHAR(32); the id must fit.
    assert len("0023_drop_lipsync_adv_fields") <= 32


def _legacy_request_with_advanced_lipsync() -> dict:
    """A digital_human_video request as persisted before #115: a full, otherwise
    valid request whose lipsync block still carries the three removed keys."""
    request = DigitalHumanVideoRequest(
        case_id="case_legacy", script="hi", voice=VoiceOptions(voice_id="voice_demo")
    ).model_dump(mode="json")
    request["lipsync"]["ref_image_artifact_id"] = "art_ref_legacy"
    request["lipsync"]["video_extension"] = True
    request["lipsync"]["query_face_threshold"] = 0.5
    return request


def test_upgrade_strips_unwired_lipsync_keys(db_session_factory):
    legacy_request = _legacy_request_with_advanced_lipsync()

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

    lipsync = stored["lipsync"]
    assert "ref_image_artifact_id" not in lipsync
    assert "video_extension" not in lipsync
    assert "query_face_threshold" not in lipsync
    # Untouched supported fields survive.
    assert lipsync["enabled"] is True
    assert lipsync["timeout_minutes"] == 30
    # The migrated row now validates cleanly against the slimmed contract.
    DigitalHumanVideoRequest.model_validate(stored)


def test_upgrade_is_idempotent_and_skips_non_digital_human(db_session_factory):
    legacy_request = _legacy_request_with_advanced_lipsync()
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

    assert "video_extension" not in dh_request["lipsync"]
    assert "ref_image_artifact_id" not in dh_request["lipsync"]
    assert "query_face_threshold" not in dh_request["lipsync"]
    # Non digital_human_video rows are never touched.
    assert kept_request == other_request
