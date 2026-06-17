from __future__ import annotations

import json
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from packages.core.contracts import RewardSignal
from packages.core.storage.database import (
    CaseRow,
    FinishedVideoRow,
    RewardSignalRow,
    ScriptVersionRow,
    VideoVersionRow,
)
from packages.creative.cases import SqlAlchemyCaseRubricRepository


sqlite3.register_adapter(dict, json.dumps)
sqlite3.register_adapter(list, json.dumps)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _repository_with_sqlite():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        CaseRow.__table__,
        ScriptVersionRow.__table__,
        VideoVersionRow.__table__,
        FinishedVideoRow.__table__,
        RewardSignalRow.__table__,
    ):
        table.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add_all(
            [
                CaseRow(id="case_a", name="A", status="active", description=""),
                CaseRow(id="case_b", name="B", status="active", description=""),
                ScriptVersionRow(
                    id="sv_a",
                    case_id="case_a",
                    title="Script A",
                    script="A script",
                ),
                VideoVersionRow(
                    id="vv_a",
                    case_id="case_a",
                    script_version_id="sv_a",
                    finished_video_id="fv_a",
                    timeline_plan_artifact_id="art_timeline",
                    style_plan_artifact_id="art_style",
                ),
                FinishedVideoRow(
                    id="fv_a",
                    case_id="case_a",
                    title="Video A",
                    video_artifact={
                        "artifact_id": "art_video",
                        "kind": "video.final",
                        "uri": "local://cutagent-local/a.mp4",
                    },
                    duration_sec=12,
                    qc_status="passed",
                ),
            ]
        )
        session.commit()
    return SqlAlchemyCaseRubricRepository(session_factory), session_factory


def test_lineage_resolvers_are_scoped_by_case_id():
    repository, _ = _repository_with_sqlite()

    assert repository.get_script_version("case_a", "sv_a") is not None
    assert repository.get_script_version("case_b", "sv_a") is None
    assert repository.resolve_video_version("case_a", "vv_a") is not None
    assert repository.resolve_video_version("case_b", "vv_a") is None
    assert repository.resolve_video_version_for_finished_video("case_a", "fv_a") is not None
    assert repository.resolve_video_version_for_finished_video("case_b", "fv_a") is None
    assert repository.resolve_script_version_for_finished_video("case_a", "fv_a") == "sv_a"
    assert repository.resolve_script_version_for_finished_video("case_b", "fv_a") is None


def test_reward_dedupe_is_scoped_by_case_id():
    repository, _ = _repository_with_sqlite()

    first = repository.add_reward(
        RewardSignal(
            id="reward_1",
            case_id="case_a",
            source_kind="published",
            value=0.6,
            confidence=0.7,
            evidence_ref="evidence_shared",
        )
    )
    second = repository.add_reward(
        RewardSignal(
            id="reward_2",
            case_id="case_a",
            source_kind="published",
            value=0.1,
            confidence=0.2,
            evidence_ref="evidence_shared",
        )
    )

    assert second.id == first.id
    assert repository.reward_exists("case_a", "published", "evidence_shared") is True
    assert repository.reward_exists("case_b", "published", "evidence_shared") is False
    assert len(repository.list_rewards("case_a")) == 1
