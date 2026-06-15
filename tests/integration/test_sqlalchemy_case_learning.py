import os

import pytest
from fastapi.testclient import TestClient

if os.getenv("CUTAGENT_RUN_DB_TESTS") != "1":
    pytest.skip("Set CUTAGENT_RUN_DB_TESTS=1 to run database integration tests.", allow_module_level=True)

from apps.api.main import app
from packages.core.storage.bootstrap import get_sqlalchemy_session_factory_if_enabled
from uuid import uuid4

from packages.core.storage.database import (
    CaseMemoryRow,
    MemoryProposalRow,
    PerformanceObservationRow,
    PerformanceScoreRow,
    PublishRecordRow,
    ScriptDraftRow,
    ScriptVersionRow,
)
from packages.core.contracts import utcnow


def sqlalchemy_session_factory():
    session_factory = get_sqlalchemy_session_factory_if_enabled()
    if session_factory is None:
        pytest.skip("Set CUTAGENT_STORAGE_BACKEND=sqlalchemy to run database integration tests.")
    return session_factory


def test_sqlalchemy_case_agent_learning_boundary_is_persisted():
    session_factory = sqlalchemy_session_factory()

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert admin_login.status_code == 200, admin_login.text

        created_binding = client.post(
            "/api/cases/case_demo/agent/source-bindings",
            json={
                "source_type": "text",
                "source_ref": "Audience wants concrete proof in the first three seconds.",
                "title": "Audience note",
            },
        )
        assert created_binding.status_code == 201, created_binding.text
        binding = created_binding.json()

        listed_bindings = client.get("/api/cases/case_demo/agent/source-bindings")
        assert listed_bindings.status_code == 200, listed_bindings.text
        assert any(item["id"] == binding["id"] for item in listed_bindings.json()["items"])

        imported = client.post(
            "/api/cases/case_demo/agent/import-source",
            json={"source_binding_id": binding["id"]},
        )
        assert imported.status_code == 202, imported.text
        import_run = imported.json()
        assert import_run["goal"] == "brief"

        run_detail = client.get(f"/api/cases/case_demo/agent/runs/{import_run['id']}")
        assert run_detail.status_code == 200, run_detail.text
        briefs = run_detail.json()["briefs"]
        assert briefs
        # F/#2: import-source emits a real CreativeBrief from the bound source
        # content (§32.4 fields), not the old "Imported source summary." stub.
        imported_brief = next(
            (item for item in briefs if item.get("generated_by_run_id") == import_run["id"]),
            briefs[-1],
        )
        assert imported_brief["summary"] != "Imported source summary."
        assert imported_brief["summary"]
        assert imported_brief["key_insights"]
        assert imported_brief["source_refs"]
        assert imported_brief["generated_by_run_id"] == import_run["id"]

        script_run = client.post(
            "/api/cases/case_demo/agent/runs",
            json={"goal": "script_draft", "source_binding_ids": [binding["id"]]},
        )
        assert script_run.status_code == 202, script_run.text

        drafts = client.get("/api/cases/case_demo/agent/drafts")
        assert drafts.status_code == 200, drafts.text
        draft = next(item for item in drafts.json()["items"] if item["status"] == "draft")

        adopted = client.post(
            f"/api/cases/case_demo/agent/drafts/{draft['id']}/adopt",
            json={"title": "Adopted proof-first script", "publish_content": "Proof first. Then offer."},
        )
        assert adopted.status_code == 201, adopted.text
        script_version = adopted.json()
        assert script_version["adopted_from_draft_id"] == draft["id"]

        memory_run = client.post("/api/cases/case_demo/agent/runs", json={"goal": "memory_proposal"})
        assert memory_run.status_code == 202, memory_run.text
        memory_run_id = memory_run.json()["id"]

        proposals = client.get("/api/cases/case_demo/agent/memory-proposals")
        assert proposals.status_code == 200, proposals.text
        proposal = next(
            item
            for item in proposals.json()["items"]
            if item["status"] == "proposed" and item.get("proposed_by_reflection_run_id") == memory_run_id
        )

        memory_before = client.get("/api/cases/case_demo/memory")
        assert memory_before.status_code == 200, memory_before.text
        assert all(item["id"] != proposal["id"] for item in memory_before.json()["items"])

        approved = client.post(f"/api/cases/case_demo/memory/{proposal['id']}/approve", json={})
        assert approved.status_code == 200, approved.text
        memory = approved.json()
        assert memory["status"] == "active"

        memory_after = client.get("/api/cases/case_demo/memory")
        assert memory_after.status_code == 200, memory_after.text
        assert any(item["id"] == memory["id"] for item in memory_after.json()["items"])

        knowledge = client.get("/api/cases/case_demo/knowledge")
        assert knowledge.status_code == 200, knowledge.text
        knowledge_body = knowledge.json()
        assert any(item["id"] == memory["id"] for item in knowledge_body["memories"])
        assert any(item["id"] == script_version["id"] for item in knowledge_body["recent_script_versions"])

        generated = client.post(
            "/api/cases/case_demo/scripts/generate-with-memory",
            json={"brief": "Make this feel specific.", "memory_ids": [memory["id"]]},
        )
        assert generated.status_code == 202, generated.text
        assert generated.json()["memory_ids"] == [memory["id"]]

        reflection = client.post("/api/cases/case_demo/reflection-runs", json={"window": "7d"})
        assert reflection.status_code == 202, reflection.text
        reflection_id = reflection.json()["id"]

        proposals_after_reflection = client.get("/api/cases/case_demo/agent/memory-proposals")
        assert proposals_after_reflection.status_code == 200, proposals_after_reflection.text
        reflection_proposal = next(
            item
            for item in proposals_after_reflection.json()["items"]
            if item.get("proposed_by_reflection_run_id") == reflection_id
        )

        rejected = client.post(
            f"/api/cases/case_demo/memory/{reflection_proposal['id']}/reject",
            json={"reason": "Needs more evidence"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

        insights = client.get("/api/cases/case_demo/insights")
        assert insights.status_code == 200, insights.text
        assert insights.json()["items"][0]["title"] == "Memory proposals"

        patterns = client.get("/api/cases/case_demo/creative-patterns")
        assert patterns.status_code == 200, patterns.text
        assert patterns.json()["items"][0]["label"]

    with session_factory() as session:
        assert session.get(ScriptVersionRow, script_version["id"]) is not None
        assert session.get(ScriptDraftRow, generated.json()["id"]) is not None
        assert session.get(CaseMemoryRow, memory["id"]) is not None
        rejected_row = session.get(MemoryProposalRow, reflection_proposal["id"])
        assert rejected_row is not None
        assert rejected_row.status == "rejected"


def test_sqlalchemy_metrics_import_matched_row_persists_observation_and_score():
    """DB-path metrics import must not raise on the happy (matched) path.

    Regression for the blocker where import_metrics scored a contract obtained
    from an *unflushed* ORM row (None created_at/updated_at/schema_version),
    raising a pydantic ValidationError -> HTTP 500 on every matched row.
    """
    session_factory = sqlalchemy_session_factory()
    suffix = uuid4().hex[:8]
    publish_record_id = f"pub_metrics_{suffix}"

    with session_factory() as session:
        session.add(
            PublishRecordRow(
                id=publish_record_id,
                case_id="case_demo",
                platform="douyin",
                status="published",
                published_at=utcnow(),
            )
        )
        session.commit()

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert admin_login.status_code == 200, admin_login.text

        # Bind by the operator-supplied publish_record_id (deterministic, not a
        # title/time guess) so the row matches regardless of matching_policy.
        response = client.post(
            "/api/cases/case_demo/metrics/import",
            json={
                "rows": [
                    {
                        "publish_record_id": publish_record_id,
                        "impressions": 50000,
                        "views": 12000,
                        "completion_rate": 0.42,
                        "metric_name": "completion_rate",
                        "metric_value": 0.42,
                        "window": "7d",
                    }
                ],
                "matching_policy": "strict_manual",
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["created_count"] == 1
        assert body["skipped_count"] == 0
        observation_id = body["results"][0]["internal_id"]

    with session_factory() as session:
        obs_row = session.get(PerformanceObservationRow, observation_id)
        assert obs_row is not None
        assert obs_row.publish_record_id == publish_record_id
        assert obs_row.impressions == 50000
        assert obs_row.created_at is not None
        score_rows = list(
            session.query(PerformanceScoreRow).filter(
                PerformanceScoreRow.observation_id == observation_id
            )
        )
        assert len(score_rows) == 1
        assert score_rows[0].normalized_score == 0.42
