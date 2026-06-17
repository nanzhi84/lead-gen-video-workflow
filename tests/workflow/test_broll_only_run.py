from __future__ import annotations

from packages.ai.gateway import ProviderGateway
from packages.ai.prompts import PromptRegistry
from packages.core.contracts import (
    AnnotationEditorVm,
    AnnotationMetaV4,
    AnnotationV4,
    ArtifactKind,
    ClipRetrievalV4,
    ClipSemanticsV4,
    ClipUsageV4,
    ClipV4,
    DigitalHumanVideoRequest,
    Job,
    JobStatus,
    JobType,
    NodeStatus,
    RunStatus,
    UsageRole,
    WorkflowRun,
)
from packages.core.storage.object_store import LocalObjectStore
from packages.core.storage.repository import Repository
from packages.media.assets import store_file
from packages.media.video.ffmpeg import probe_media
from packages.production.pipeline.digital_human import (
    build_digital_human_workflow,
    template_for,
)
from packages.production.pipeline.node_sequence import BROLL_ONLY_SEQUENCE


def _seed_long_broll(repository: Repository, object_store, media_fixture_factory) -> None:
    source = media_fixture_factory.video(
        duration_sec=10.0,
        width=320,
        height=180,
        fps=12,
        filename="broll_only_e2e_source.mp4",
    )
    stored = store_file(object_store, source, purpose="seed-media")
    media_info = probe_media(source)
    artifact = repository.create_artifact(
        kind=ArtifactKind.uploaded_file,
        payload_schema="UploadedFileArtifact.v1",
        payload={
            "upload_session_id": None,
            "filename": source.name,
            "content_type": "video/mp4",
            "size_bytes": source.stat().st_size,
            "object_uri": stored.ref.uri,
            "sha256": stored.sha256,
            "metadata": {"asset_id": "asset_broll_demo"},
        },
        case_id="case_demo",
        uri=stored.ref.uri,
        sha256=stored.sha256,
        media_info=media_info,
    )
    repository.media_assets["asset_broll_demo"] = repository.media_assets[
        "asset_broll_demo"
    ].model_copy(update={"source_artifact_id": artifact.id})
    repository.annotations["asset_broll_demo"] = AnnotationEditorVm(
        asset=repository.media_assets["asset_broll_demo"],
        etag="broll-only-e2e",
        canonical=AnnotationV4(
            meta=AnnotationMetaV4(
                asset_id="asset_broll_demo",
                case_id="case_demo",
                material_type="broll",
                duration=10.0,
            ),
            clips=[
                ClipV4(
                    segment_id="cover_process",
                    start=0.0,
                    end=5.0,
                    duration=5.0,
                    semantics=ClipSemanticsV4(
                        scene_type="施工过程",
                        action="补漆修复",
                        narrative_role="施工过程",
                    ),
                    usage=ClipUsageV4(role=UsageRole.cover, recommended_for_voiceover=True),
                    retrieval=ClipRetrievalV4(
                        summary="施工过程补漆修复展示",
                        keywords=["施工过程", "补漆", "修复", "展示"],
                        retrieval_sentence="展示施工过程和补漆修复细节",
                    ),
                    confidence=0.95,
                ),
                ClipV4(
                    segment_id="cover_result",
                    start=5.0,
                    end=10.0,
                    duration=5.0,
                    semantics=ClipSemanticsV4(
                        scene_type="效果展示",
                        action="完工展示",
                        narrative_role="效果展示",
                    ),
                    usage=ClipUsageV4(role=UsageRole.cover, recommended_for_voiceover=True),
                    retrieval=ClipRetrievalV4(
                        summary="完工效果展示",
                        keywords=["效果展示", "完工", "展示"],
                        retrieval_sentence="展示完工后的效果",
                    ),
                    confidence=0.95,
                ),
            ],
            quality_report={"usable_ratio": 0.95},
        ),
        projection={},
    )


def test_broll_only_run_finishes_without_a_roll_artifacts(
    tmp_path,
    media_fixture_factory,
    monkeypatch,
):
    object_store = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(
        "packages.production.pipeline.digital_human.get_object_store",
        lambda: object_store,
    )
    repository = Repository()
    _seed_long_broll(repository, object_store, media_fixture_factory)
    runtime = build_digital_human_workflow(
        repository,
        provider_gateway=ProviderGateway(repository, object_store=object_store),
        prompt_registry=PromptRegistry(repository),
        seed_media=False,
    )
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        title="仅 B_roll 画外音",
        script="施工过程展示补漆修复。效果展示完工后的变化。",
        voice={"voice_id": "voice_sandbox"},
        workflow_template_id="broll_only_v1",
        broll={"enabled": True, "min_segment_duration": 1.0},
        bgm={"enabled": False},
        output={"width": 160, "height": 90, "fps": 12},
        strictness={"strict_timestamps": False},
    )
    job = Job(
        id="job_broll_only",
        type=JobType.digital_human_video,
        status=JobStatus.queued,
        case_id="case_demo",
        created_by="usr_admin",
        request_schema=request.schema_version,
        request=request,
    )
    template = template_for(request.workflow_template_id)
    run = WorkflowRun(
        id="run_broll_only",
        job_id=job.id,
        case_id="case_demo",
        workflow_template_id=template.workflow_template_id,
        workflow_version=template.version,
        status=RunStatus.admitted,
        requested_by="usr_admin",
    )
    repository.jobs[job.id] = job
    repository.runs[run.id] = run
    repository.node_runs[run.id] = []

    runtime.start_run(job=job, run=run, template=template)

    finished_run = repository.runs[run.id]
    produced_kinds = {artifact.kind for artifact in repository.artifacts.values()}
    node_ids = [node.node_id for node in repository.node_runs[run.id]]

    assert finished_run.status == RunStatus.succeeded
    assert ArtifactKind.video_finished in produced_kinds
    assert ArtifactKind.plan_portrait not in produced_kinds
    assert ArtifactKind.video_portrait_track not in produced_kinds
    assert ArtifactKind.video_lipsync not in produced_kinds
    assert len(repository.node_runs[run.id]) == 13
    assert node_ids == BROLL_ONLY_SEQUENCE
    assert all(
        node.status in {NodeStatus.succeeded, NodeStatus.degraded, NodeStatus.skipped}
        for node in repository.node_runs[run.id]
    )
