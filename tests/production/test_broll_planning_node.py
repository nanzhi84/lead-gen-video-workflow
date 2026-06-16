from __future__ import annotations

import pytest

from packages.core.contracts import (
    Artifact,
    ArtifactKind,
    DigitalHumanVideoRequest,
    NodeRun,
    NodeStatus,
    RunStatus,
    WorkflowRun,
)
from packages.core.storage.repository import Repository
from packages.planning.material.broll_plan import BrollInsertion
from packages.production.pipeline import nodes
from packages.production.pipeline._node_context import NodeContext
from packages.production.pipeline._run_state import RunState
from packages.production.pipeline.digital_human import LocalRuntimeAdapter


def _artifact(kind: ArtifactKind, payload: dict) -> Artifact:
    return Artifact(
        id=f"art_{kind.value.replace('.', '_')}",
        case_id="case_demo",
        run_id="run_broll",
        node_run_id="nr_input",
        kind=kind,
        payload=payload,
        payload_schema=f"{kind.value}.v1",
    )


def _run() -> WorkflowRun:
    return WorkflowRun(
        id="run_broll",
        job_id="job_broll",
        case_id="case_demo",
        workflow_template_id="digital_human_v2",
        workflow_version="v1",
        status=RunStatus.running,
    )


def _node_run() -> NodeRun:
    return NodeRun(
        id="nr_broll",
        run_id="run_broll",
        node_id="BrollPlanning",
        node_version="v1",
        status=NodeStatus.running,
        input_manifest_hash="sha256:test",
    )


def test_broll_planning_outputs_clip_id_on_segments_and_overlays(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = Repository()
    adapter = object.__new__(LocalRuntimeAdapter)
    adapter.repository = repository
    state = RunState(
        request=DigitalHumanVideoRequest(
            case_id="case_demo",
            script="hello",
            voice={"voice_id": "voice_sandbox"},
            broll={"enabled": True, "max_inserts": 1},
        ),
        artifacts={
            ArtifactKind.plan_material_pack: _artifact(
                ArtifactKind.plan_material_pack,
                {"broll_candidates": [{"asset_id": "asset_broll_demo"}]},
            ),
            ArtifactKind.narration_units: _artifact(
                ArtifactKind.narration_units,
                {
                    "units": [
                        {
                            "unit_id": "unit_1",
                            "text": "hello",
                            "start": 0.0,
                            "end": 3.0,
                            "confidence": 0.9,
                        }
                    ]
                },
            ),
        },
    )
    insertion = BrollInsertion(
        asset_id="asset_broll_demo",
        clip_id="cover_a",
        timeline_start=0.0,
        timeline_end=2.0,
        source_start=1.0,
        source_end=3.0,
        confidence=0.8,
        matched_keywords=("hello",),
        scene_name="demo",
        reason="matched",
        diversity_key="scene:demo",
    )
    monkeypatch.setattr(nodes.broll_planning, "rank_broll_candidates", lambda **_: [])
    monkeypatch.setattr(nodes.broll_planning, "plan_insertions", lambda **_: [insertion])

    ctx = NodeContext(adapter=adapter, run=_run(), node_run=_node_run(), state=state)
    output = nodes.broll_planning.run(ctx)
    payload = next(
        artifact.payload
        for artifact in output.artifacts
        if artifact.kind == ArtifactKind.plan_broll
    )

    assert payload["segments"][0]["clip_id"] == "cover_a"
    assert payload["overlays"][0]["clip_id"] == "cover_a"
