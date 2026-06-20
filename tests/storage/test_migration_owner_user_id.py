from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from packages.core.storage.database import (
    FinishedVideoRow,
    JobRow,
    UserRow,
    WorkflowRunRow,
    YieldFunnelEventRow,
)
from packages.core.storage.repository import new_id


sqlite3.register_adapter(dict, json.dumps)
sqlite3.register_adapter(list, json.dumps)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw):
    return "JSON"


MIGRATION_PATH = Path(
    "packages/core/storage/alembic/versions/0018_owner_user_id_isolation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig_0018", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_orm_models_expose_owner_user_id_column():
    assert "owner_user_id" in FinishedVideoRow.__table__.columns
    assert "owner_user_id" in YieldFunnelEventRow.__table__.columns


def test_migration_revision_chains_to_0017():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "0018_owner_user_id_isolation"' in text
    assert 'down_revision = "0017_secret_encrypted_value"' in text


def _build_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        UserRow.__table__,
        JobRow.__table__,
        WorkflowRunRow.__table__,
        FinishedVideoRow.__table__,
        YieldFunnelEventRow.__table__,
    ):
        table.create(engine)
    return engine


def _run_upgrade(engine, module):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()


def test_backfill_resolves_owner_via_run_and_job_chain():
    module = _load_migration()
    engine = _build_engine()

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(UserRow(id="usr_alice", email="a@example.com", password_hash="x", role="operator", status="active", display_name="x"))
        session.add(
            JobRow(
                id="job_1",
                type="digital_human_video",
                status="succeeded",
                created_by="usr_alice",
                request_schema="DigitalHumanVideoRequest.v1",
                request={},
            )
        )
        session.add(
            WorkflowRunRow(
                id="run_1",
                job_id="job_1",
                workflow_template_id="tpl",
                workflow_version="1",
                status="succeeded",
                requested_by="usr_alice",
            )
        )
        # Linked finished video -> backfilled to alice
        session.add(
            FinishedVideoRow(
                id="fv_linked",
                case_id="case_1",
                run_id="run_1",
                title="linked",
                video_artifact={},
                qc_status="passed",
            )
        )
        # Orphan finished video (no run) -> stays NULL
        session.add(
            FinishedVideoRow(
                id="fv_orphan",
                case_id="case_1",
                run_id=None,
                title="orphan",
                video_artifact={},
                qc_status="passed",
            )
        )
        session.commit()

    _run_upgrade(engine, module)

    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                sa.text("SELECT id, owner_user_id FROM finished_videos")
            ).all()
        )
    assert rows["fv_linked"] == "usr_alice"
    assert rows["fv_orphan"] is None


def test_backfill_yield_funnel_events_priority_and_orphan():
    module = _load_migration()
    engine = _build_engine()

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(UserRow(id="usr_bob", email="b@example.com", password_hash="x", role="operator", status="active", display_name="x"))
        session.add(
            JobRow(
                id="job_b",
                type="digital_human_video",
                status="succeeded",
                created_by="usr_bob",
                request_schema="DigitalHumanVideoRequest.v1",
                request={},
            )
        )
        session.add(
            WorkflowRunRow(
                id="run_b",
                job_id="job_b",
                workflow_template_id="tpl",
                workflow_version="1",
                status="succeeded",
                requested_by="usr_bob",
            )
        )
        session.add(
            FinishedVideoRow(
                id="fv_b",
                case_id="case_b",
                run_id="run_b",
                title="t",
                video_artifact={},
                qc_status="passed",
                owner_user_id="usr_bob",
            )
        )
        # event via run_id
        session.add(
            YieldFunnelEventRow(
                id="evt_run",
                run_id="run_b",
                event_type="run_started",
                event_time=__import__("datetime").datetime(2026, 1, 1),
                dedupe_key=new_id("dk"),
            )
        )
        # event via job_id only
        session.add(
            YieldFunnelEventRow(
                id="evt_job",
                job_id="job_b",
                event_type="job_created",
                event_time=__import__("datetime").datetime(2026, 1, 1),
                dedupe_key=new_id("dk"),
            )
        )
        # event via finished_video_id only
        session.add(
            YieldFunnelEventRow(
                id="evt_fv",
                finished_video_id="fv_b",
                event_type="finished",
                event_time=__import__("datetime").datetime(2026, 1, 1),
                dedupe_key=new_id("dk"),
            )
        )
        # orphan event (no links) -> NULL
        session.add(
            YieldFunnelEventRow(
                id="evt_orphan",
                event_type="noop",
                event_time=__import__("datetime").datetime(2026, 1, 1),
                dedupe_key=new_id("dk"),
            )
        )
        session.commit()

    _run_upgrade(engine, module)

    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                sa.text("SELECT id, owner_user_id FROM yield_funnel_events")
            ).all()
        )
    assert rows["evt_run"] == "usr_bob"
    assert rows["evt_job"] == "usr_bob"
    assert rows["evt_fv"] == "usr_bob"
    assert rows["evt_orphan"] is None
