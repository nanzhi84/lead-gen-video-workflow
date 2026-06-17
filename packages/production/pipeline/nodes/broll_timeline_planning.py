"""BrollTimelinePlanning node: build a B-roll-only render timeline."""

from __future__ import annotations

from packages.core.contracts import ArtifactKind, ErrorCode
from packages.core.contracts.artifacts import RenderPlanArtifact, TimelinePlanArtifact
from packages.core.workflow import NodeExecutionError, NodeOutput
from packages.production.pipeline._node_context import NodeContext
from packages.production.pipeline._timeline_grid import build_tracks, to_frame, validate_timeline


def run(ctx: NodeContext) -> NodeOutput:
    state = ctx.state
    repository = ctx.repository
    audio = state.require(ArtifactKind.audio_tts)
    broll_artifact = state.require(ArtifactKind.plan_broll)
    broll = broll_artifact.payload or {}

    duration = float((audio.media_info.duration_sec if audio.media_info else 0) or 0)
    if duration <= 0:
        raise NodeExecutionError(ErrorCode.render_invalid_timeline, "Timeline duration is invalid.")
    fps = int(state.request.output.fps)
    total_frames = max(1, round(duration * fps))

    raw_segments: list[dict] = []
    for index, segment in enumerate(broll.get("segments", [])):
        start_sec = float(segment.get("start_sec", segment.get("timeline_start", 0)) or 0)
        end_sec = float(segment.get("end_sec", segment.get("timeline_end", 0)) or 0)
        raw_segments.append(
            {
                "track_id": "broll",
                "segment_id": f"broll_{index + 1}",
                "asset_ref": repository.artifact_ref(broll_artifact.id),
                "start_sec": start_sec,
                "end_sec": end_sec,
                "source_start_sec": float(segment.get("source_start", 0) or 0),
                "source_end_sec": float(segment.get("source_end", end_sec) or 0),
                "timeline_start_frame": to_frame(start_sec, fps),
                "timeline_end_frame": to_frame(end_sec, fps),
                "source_start_frame": None,
                "source_end_frame": None,
            }
        )

    validation = validate_timeline(raw_segments, fps, total_frames)
    if not validation.valid:
        raise NodeExecutionError(ErrorCode.render_invalid_timeline, "Timeline validation failed.")

    tracks = build_tracks(raw_segments, fps)
    timeline = TimelinePlanArtifact(
        fps=fps,
        total_frames=total_frames,
        tracks=tracks,
        validation=validation,
    )
    render_plan = RenderPlanArtifact(
        timeline_artifact_id="pending",
        render_size=(state.request.output.width, state.request.output.height),
        fps=fps,
        tracks=tracks,
    )
    timeline_artifact = ctx.artifact(
        ArtifactKind.plan_timeline,
        timeline.model_dump(mode="json"),
        "TimelinePlanArtifact.v1",
    )
    render_plan = render_plan.model_copy(update={"timeline_artifact_id": timeline_artifact.id})
    return NodeOutput(
        artifacts=[
            timeline_artifact,
            ctx.artifact(
                ArtifactKind.plan_render,
                render_plan.model_dump(mode="json"),
                "RenderPlanArtifact.v1",
            ),
        ]
    )
