"""Regression test for SqlAlchemyProductionRepository.delete_run_record.

This path was silently broken: it queried ``MediaAssetRow.node_run_id`` — a column
that never existed on MediaAssetRow — so deleting any run that had node runs raised
AttributeError (500). The broken block was removed; this test pins that delete works
end to end and detaches run/node_run references from the rows that DO carry them
(artifacts, provider invocations, prompt invocations) while preserving finished videos.
"""

import json
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from packages.core.storage.database import (
    ArtifactRow,
    CaseRow,
    FinishedVideoRow,
    JobRow,
    NodeRunRow,
    PromptInvocationRow,
    ProviderInvocationRow,
    WorkflowRunRow,
    YieldFunnelEventRow,
)
from packages.production import SqlAlchemyProductionRepository


sqlite3.register_adapter(list, json.dumps)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw):
    return "JSON"


_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repository_with_sqlite():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        CaseRow.__table__,
        JobRow.__table__,
        WorkflowRunRow.__table__,
        NodeRunRow.__table__,
        ArtifactRow.__table__,
        ProviderInvocationRow.__table__,
        PromptInvocationRow.__table__,
        FinishedVideoRow.__table__,
        YieldFunnelEventRow.__table__,
    ):
        table.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyProductionRepository(session_factory), session_factory


def _seed_run(session_factory) -> tuple[str, str]:
    """A succeeded (deletable) run with one node run plus rows that reference it."""
    run_id, node_run_id = "run_1", "nr_1"
    with session_factory() as session:
        session.add(CaseRow(id="case_demo", name="c", owner_user_id="usr_admin", status="active", description=""))
        session.add(JobRow(id="job_1", type="production", status="succeeded", request_schema="X.v1", request={}))
        session.add(
            WorkflowRunRow(
                id=run_id,
                job_id="job_1",
                case_id="case_demo",
                workflow_template_id="production",
                workflow_version="1",
                status="succeeded",
            )
        )
        session.add(
            NodeRunRow(
                id=node_run_id,
                run_id=run_id,
                node_id="lipsync",
                node_version="1",
                status="succeeded",
                input_manifest_hash="hash",
            )
        )
        session.add(
            ArtifactRow(
                id="art_1",
                case_id="case_demo",
                run_id=run_id,
                node_run_id=node_run_id,
                kind="video.finished",
                payload_schema="X.v1",
            )
        )
        session.add(
            ProviderInvocationRow(
                id="pi_1",
                run_id=run_id,
                node_run_id=node_run_id,
                provider_id="p",
                model_id="m",
                provider_profile_id="pp",
                capability_id="cap",
                status="succeeded",
            )
        )
        session.add(
            PromptInvocationRow(
                id="pri_1",
                prompt_template_id="pt",
                prompt_version_id="pv",
                run_id=run_id,
                node_run_id=node_run_id,
                status="succeeded",
            )
        )
        session.add(
            FinishedVideoRow(
                id="fv_1",
                case_id="case_demo",
                run_id=run_id,
                title="t",
                video_artifact={"artifact_id": "art_1"},
                qc_status="pending",
            )
        )
        session.add(
            YieldFunnelEventRow(
                id="yf_1",
                run_id=run_id,
                event_type="run_started",
                event_time=_NOW,
                dedupe_key="yf_1",
            )
        )
        session.commit()
    return run_id, node_run_id


def test_delete_run_record_with_node_runs_succeeds_and_detaches_references():
    repository, session_factory = _repository_with_sqlite()
    run_id, node_run_id = _seed_run(session_factory)

    # The formerly-broken MediaAssetRow.node_run_id query fired whenever node_ids was
    # non-empty; this run has a node run, so a regression would raise here.
    deleted = repository.delete_run_record(run_id)
    assert deleted is True

    with session_factory() as session:
        assert session.get(WorkflowRunRow, run_id) is None
        assert session.get(NodeRunRow, node_run_id) is None

        artifact = session.get(ArtifactRow, "art_1")
        assert artifact is not None and artifact.run_id is None and artifact.node_run_id is None

        provider = session.get(ProviderInvocationRow, "pi_1")
        assert provider is not None and provider.run_id is None and provider.node_run_id is None

        prompt = session.get(PromptInvocationRow, "pri_1")
        assert prompt is not None and prompt.run_id is None and prompt.node_run_id is None

        # Finished videos are preserved (only detached from the deleted run).
        finished = session.get(FinishedVideoRow, "fv_1")
        assert finished is not None and finished.run_id is None

        event = session.get(YieldFunnelEventRow, "yf_1")
        assert event is not None and event.run_id is None


def test_delete_run_record_returns_false_for_unknown_run():
    repository, _ = _repository_with_sqlite()
    assert repository.delete_run_record("nope") is False
