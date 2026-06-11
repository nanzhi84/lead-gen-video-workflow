from __future__ import annotations

from dataclasses import dataclass, field

from packages.ai.gateway import ProviderCall, ProviderGateway, get_provider_gateway
from packages.ai.prompts import PromptRegistry, get_prompt_registry
from packages.core.contracts import (
    Artifact,
    ArtifactKind,
    DegradationCode,
    DigitalHumanVideoRequest,
    ErrorCode,
    FinishedVideo,
    Job,
    NodeRun,
    NodeStatus,
    JobStatus,
    RunDebugReportArtifact,
    RunPublicReportArtifact,
    RunStatus,
    ScriptVersion,
    ValidatedProductionSpec,
    VideoVersion,
    WarningCode,
    WorkflowRun,
    WorkflowTemplate,
    NodeSpec,
    WorkflowEdge,
    utcnow,
)
from packages.core.storage import Repository, get_repository
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError, NodeOutput, WorkflowRuntimeAdapter, manifest_hash


NODE_SEQUENCE = [
    "ValidateRequest",
    "LoadCaseContext",
    "ResolveCreativeIntent",
    "TTS",
    "MaterialPackPlanning",
    "NarrationAlignment",
    "PortraitPlanning",
    "BrollPlanning",
    "StylePlanning",
    "TimelinePlanning",
    "PortraitTrackBuild",
    "LipSync",
    "RenderFinalTimeline",
    "SubtitleAndBgmMix",
    "ExportFinishedVideo",
    "FinalizeRunReport",
]


def digital_human_template() -> WorkflowTemplate:
    nodes = [
        NodeSpec(
            node_id=node_id,
            input_schema=f"{node_id}.input.v1",
            output_artifact_kinds=[],
            side_effects=["provider_call"] if node_id in {"TTS", "ResolveCreativeIntent", "LipSync"} else [],
        )
        for node_id in NODE_SEQUENCE
    ]
    for spec in nodes:
        if spec.node_id == "ValidateRequest":
            spec.output_artifact_kinds.append(ArtifactKind.validated_production_spec)
        elif spec.node_id == "LoadCaseContext":
            spec.output_artifact_kinds.append(ArtifactKind.case_context)
        elif spec.node_id == "ResolveCreativeIntent":
            spec.output_artifact_kinds.append(ArtifactKind.creative_intent)
        elif spec.node_id == "TTS":
            spec.output_artifact_kinds.append(ArtifactKind.audio_tts)
        elif spec.node_id == "MaterialPackPlanning":
            spec.output_artifact_kinds.append(ArtifactKind.plan_material_pack)
        elif spec.node_id == "NarrationAlignment":
            spec.output_artifact_kinds.extend([ArtifactKind.audio_alignment, ArtifactKind.narration_units])
        elif spec.node_id == "PortraitPlanning":
            spec.output_artifact_kinds.append(ArtifactKind.plan_portrait)
        elif spec.node_id == "BrollPlanning":
            spec.output_artifact_kinds.append(ArtifactKind.plan_broll)
        elif spec.node_id == "StylePlanning":
            spec.output_artifact_kinds.append(ArtifactKind.plan_style)
        elif spec.node_id == "TimelinePlanning":
            spec.output_artifact_kinds.extend([ArtifactKind.plan_timeline, ArtifactKind.plan_render])
        elif spec.node_id == "PortraitTrackBuild":
            spec.output_artifact_kinds.append(ArtifactKind.video_portrait_track)
        elif spec.node_id == "LipSync":
            spec.output_artifact_kinds.append(ArtifactKind.video_lipsync)
        elif spec.node_id == "RenderFinalTimeline":
            spec.output_artifact_kinds.append(ArtifactKind.video_rendered)
        elif spec.node_id == "SubtitleAndBgmMix":
            spec.output_artifact_kinds.extend([ArtifactKind.video_final, ArtifactKind.subtitle_ass])
        elif spec.node_id == "ExportFinishedVideo":
            spec.output_artifact_kinds.extend(
                [ArtifactKind.video_finished, ArtifactKind.cover_image, ArtifactKind.publish_package]
            )
        elif spec.node_id == "FinalizeRunReport":
            spec.output_artifact_kinds.extend(
                [ArtifactKind.run_report_public, ArtifactKind.run_report_debug]
            )
    return WorkflowTemplate(
        workflow_template_id="digital_human_v2",
        version="v1",
        nodes=nodes,
        edges=[
            WorkflowEdge(from_node_id=NODE_SEQUENCE[index], to_node_id=NODE_SEQUENCE[index + 1])
            for index in range(len(NODE_SEQUENCE) - 1)
        ],
    )


@dataclass
class RunState:
    request: DigitalHumanVideoRequest
    artifacts: dict[ArtifactKind, Artifact] = field(default_factory=dict)
    provider_invocation_ids: list[str] = field(default_factory=list)
    warnings: list[WarningCode] = field(default_factory=list)
    degradations: list[DegradationCode] = field(default_factory=list)

    def require(self, kind: ArtifactKind) -> Artifact:
        if kind not in self.artifacts:
            raise NodeExecutionError(ErrorCode.artifact_missing, f"Missing artifact {kind.value}.")
        return self.artifacts[kind]


class DigitalHumanWorkflow(WorkflowRuntimeAdapter):
    def __init__(
        self,
        repository: Repository,
        provider_gateway: ProviderGateway,
        prompt_registry: PromptRegistry,
    ) -> None:
        self.repository = repository
        self.provider_gateway = provider_gateway
        self.prompt_registry = prompt_registry
        self.template = digital_human_template()

    def start_digital_human_run(
        self,
        *,
        job_id: str,
        mode: str = "new",
        from_run_id: str | None = None,
        reason: str | None = None,
    ) -> WorkflowRun:
        job = self.repository.jobs[job_id]
        attempt = 1 + len([run for run in self.repository.runs.values() if run.job_id == job_id])
        run = WorkflowRun(
            id=new_id("run"),
            job_id=job_id,
            case_id=job.case_id,
            workflow_template_id=self.template.workflow_template_id,
            workflow_version=self.template.version,
            status=RunStatus.queued,
            run_attempt=attempt,
            resume_from_run_id=from_run_id if mode == "resume" else None,
            retry_from_run_id=from_run_id if mode == "retry" else None,
        )
        self.repository.runs[run.id] = run
        self.repository.node_runs[run.id] = []
        self.repository.jobs[job_id] = job.model_copy(
            update={"current_run_id": run.id, "status": JobStatus.running, "updated_at": utcnow()}
        )
        self.repository.create_event(
            "workflow.run.created",
            "run",
            run.id,
            {"job_id": job_id, "mode": mode, "reason": reason or ""},
        )
        self._execute(run.id, mode=mode, from_run_id=from_run_id)
        return self.repository.runs[run.id]

    def cancel_run(self, run_id: str, *, force: bool = False, reason: str | None = None) -> WorkflowRun:
        run = self.repository.runs[run_id]
        if run.status not in {RunStatus.queued, RunStatus.running}:
            raise NodeExecutionError(
                ErrorCode.workflow_invalid_transition,
                f"Run {run_id} cannot be cancelled from {run.status}.",
            )
        run = run.model_copy(
            update={"status": RunStatus.cancelled, "finished_at": utcnow(), "updated_at": utcnow()}
        )
        self.repository.runs[run.id] = run
        self.repository.create_event(
            "workflow.run.cancelled",
            "run",
            run.id,
            {"force": force, "reason": reason or ""},
        )
        return run

    def _execute(self, run_id: str, *, mode: str, from_run_id: str | None) -> None:
        run = self.repository.runs[run_id]
        job = self.repository.jobs[run.job_id]
        request = self._request(job)
        state = RunState(request=request)
        start_index = 0
        run = run.model_copy(update={"status": RunStatus.running, "started_at": utcnow()})
        self.repository.runs[run.id] = run
        if mode == "resume" and from_run_id:
            start_index = self._reuse_prefix(run, state, from_run_id)
        for index, node_id in enumerate(NODE_SEQUENCE[start_index:], start=start_index):
            if self.repository.runs[run.id].status == RunStatus.cancelled:
                return
            node_run = NodeRun(
                id=new_id("nr"),
                run_id=run.id,
                node_id=node_id,
                node_version="v1",
                status=NodeStatus.running,
                input_manifest_hash=manifest_hash(
                    {
                        "node_id": node_id,
                        "request": request.model_dump(mode="json"),
                        "artifact_refs": {
                            kind.value: artifact.id for kind, artifact in state.artifacts.items()
                        },
                    }
                ),
                started_at=utcnow(),
            )
            self.repository.node_runs[run.id].append(node_run)
            try:
                output = self._run_node(node_id, run, node_run, state)
                for artifact in output.artifacts:
                    state.artifacts[artifact.kind] = artifact
                state.provider_invocation_ids.extend(output.provider_invocation_ids)
                state.warnings.extend(output.warnings)
                state.degradations.extend(output.degradations)
                status = output.status
                if status == NodeStatus.succeeded and output.degradations:
                    status = NodeStatus.degraded
                patched = node_run.model_copy(
                    update={
                        "status": status,
                        "output_artifact_ids": [artifact.id for artifact in output.artifacts],
                        "provider_invocation_ids": output.provider_invocation_ids,
                        "warnings": output.warnings,
                        "degradations": output.degradations,
                        "finished_at": utcnow(),
                        "updated_at": utcnow(),
                    }
                )
                self.repository.node_runs[run.id][-1] = patched
            except NodeExecutionError as exc:
                error = exc.error.model_copy(
                    update={"job_id": job.id, "run_id": run.id, "node_run_id": node_run.id}
                )
                self.repository.node_runs[run.id][-1] = node_run.model_copy(
                    update={
                        "status": NodeStatus.failed,
                        "error": error,
                        "finished_at": utcnow(),
                        "updated_at": utcnow(),
                    }
                )
                self._write_report(run, state, failed=True)
                self.repository.runs[run.id] = self.repository.runs[run.id].model_copy(
                    update={"status": RunStatus.failed, "finished_at": utcnow(), "updated_at": utcnow()}
                )
                self.repository.jobs[job.id] = self.repository.jobs[job.id].model_copy(
                    update={"status": JobStatus.failed, "updated_at": utcnow()}
                )
                self.repository.create_event(
                    "workflow.node.failed",
                    "run",
                    run.id,
                    {"node_id": node_id, "error_code": error.code.value},
                )
                return
        final_status = RunStatus.degraded if state.degradations else RunStatus.succeeded
        self.repository.runs[run.id] = self.repository.runs[run.id].model_copy(
            update={"status": final_status, "finished_at": utcnow(), "updated_at": utcnow()}
        )
        self.repository.jobs[job.id] = self.repository.jobs[job.id].model_copy(
            update={
                "status": JobStatus.succeeded
                if final_status == RunStatus.succeeded
                else JobStatus.partially_succeeded
            }
        )
        self.repository.create_event(
            "workflow.run.completed",
            "run",
            run.id,
            {"status": final_status.value},
        )

    def _reuse_prefix(self, run: WorkflowRun, state: RunState, from_run_id: str) -> int:
        previous = self.repository.node_runs.get(from_run_id, [])
        reusable_statuses = {NodeStatus.succeeded, NodeStatus.degraded, NodeStatus.skipped}
        start_index = 0
        for index, previous_node_run in enumerate(previous):
            if previous_node_run.status not in reusable_statuses:
                start_index = index
                break
            for artifact_id in previous_node_run.output_artifact_ids:
                artifact = self.repository.artifacts.get(artifact_id)
                if artifact is None:
                    start_index = index
                    break
                state.artifacts[artifact.kind] = artifact
            copied = previous_node_run.model_copy(
                update={
                    "id": new_id("nr"),
                    "run_id": run.id,
                    "status": NodeStatus.skipped,
                    "updated_at": utcnow(),
                }
            )
            self.repository.node_runs[run.id].append(copied)
            start_index = index + 1
        return start_index

    def _request(self, job: Job) -> DigitalHumanVideoRequest:
        request = job.request
        if not isinstance(request, DigitalHumanVideoRequest):
            raise NodeExecutionError(
                ErrorCode.validation_invalid_options,
                "DigitalHuman workflow requires DigitalHumanVideoRequest.",
            )
        return request

    def _run_node(
        self, node_id: str, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        handlers = {
            "ValidateRequest": self._validate_request,
            "LoadCaseContext": self._load_case_context,
            "ResolveCreativeIntent": self._resolve_creative_intent,
            "TTS": self._tts,
            "MaterialPackPlanning": self._material_pack_planning,
            "NarrationAlignment": self._narration_alignment,
            "PortraitPlanning": self._portrait_planning,
            "BrollPlanning": self._broll_planning,
            "StylePlanning": self._style_planning,
            "TimelinePlanning": self._timeline_planning,
            "PortraitTrackBuild": self._portrait_track_build,
            "LipSync": self._lipsync,
            "RenderFinalTimeline": self._render_final_timeline,
            "SubtitleAndBgmMix": self._subtitle_and_bgm_mix,
            "ExportFinishedVideo": self._export_finished_video,
            "FinalizeRunReport": self._finalize_run_report,
        }
        return handlers[node_id](run, node_run, state)

    def _artifact(
        self,
        run: WorkflowRun,
        node_run: NodeRun,
        kind: ArtifactKind,
        payload,
        payload_schema: str,
        uri: str | None = None,
    ) -> Artifact:
        return self.repository.create_artifact(
            kind=kind,
            payload_schema=payload_schema,
            payload=payload,
            case_id=run.case_id,
            run_id=run.id,
            node_run_id=node_run.id,
            uri=uri,
        )

    def _validate_request(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        request = state.request
        if request.case_id not in self.repository.cases:
            raise NodeExecutionError(ErrorCode.validation_missing_case, "Case does not exist.")
        if not request.script.strip():
            raise NodeExecutionError(ErrorCode.validation_missing_script, "Script is required.")
        voice_id = request.voice.voice_id or "voice_sandbox"
        if voice_id not in self.repository.voices or not self.repository.voices[voice_id].enabled:
            raise NodeExecutionError(ErrorCode.validation_missing_voice, "Voice is missing or disabled.")
        if request.lipsync.enabled:
            profile = self.repository.provider_profiles.get(request.lipsync.provider_profile_id)
            if profile is None or profile.capability != "lipsync":
                raise NodeExecutionError(
                    ErrorCode.provider_unsupported_option,
                    "LipSync provider profile is missing or incompatible.",
                )
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.validated_production_spec,
            ValidatedProductionSpec(
                request=request,
                workflow_template_id=self.template.workflow_template_id,
                workflow_version=self.template.version,
            ).model_dump(mode="json"),
            "ValidatedProductionSpec.v1",
        )
        return NodeOutput(artifacts=[artifact])

    def _load_case_context(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        case = self.repository.cases[state.request.case_id]
        payload = {
            "case": case.model_dump(mode="json"),
            "active_memories": [
                memory.model_dump(mode="json")
                for memory in self.repository.memories.values()
                if memory.case_id == case.id and memory.status == "active"
            ],
            "recent_scripts": [
                script.model_dump(mode="json")
                for script in self.repository.scripts.values()
                if script.case_id == case.id
            ][-10:],
            "recent_finished_videos": [
                video.model_dump(mode="json")
                for video in self.repository.finished_videos.values()
                if video.case_id == case.id
            ][-10:],
            "performance_observations": [
                obs.model_dump(mode="json")
                for obs in self.repository.performance_observations.values()
                if obs.case_id == case.id
            ][-50:],
        }
        return NodeOutput(
            artifacts=[
                self._artifact(
                    run,
                    node_run,
                    ArtifactKind.case_context,
                    payload,
                    "CaseContextArtifact.v1",
                )
            ]
        )

    def _resolve_creative_intent(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        if state.request.creative_intent_ref:
            existing = self.repository.artifacts.get(state.request.creative_intent_ref.artifact_id)
            if existing is None:
                raise NodeExecutionError(ErrorCode.artifact_missing, "Creative intent artifact missing.")
            return NodeOutput(artifacts=[existing], status=NodeStatus.skipped)
        prompt_invocation, rendered = self.prompt_registry.render(
            node_id="ResolveCreativeIntent",
            variables={"script": state.request.script},
            case_id=run.case_id,
            run_id=run.id,
            node_run_id=node_run.id,
            provider_profile_id="sandbox.llm.default",
        )
        invocation, result = self.provider_gateway.invoke(
            ProviderCall(
                case_id=run.case_id,
                run_id=run.id,
                node_run_id=node_run.id,
                provider_profile_id="sandbox.llm.default",
                capability_id="llm",
                prompt_version_id=prompt_invocation.prompt_version_id,
                input={"prompt": rendered, "script": state.request.script},
            )
        )
        if result is None or invocation.error:
            raise NodeExecutionError(
                invocation.error.code if invocation.error else ErrorCode.provider_remote_failed,
                invocation.error.message if invocation.error else "Provider failed.",
                retryable=True,
            )
        self.prompt_registry.validate_output(
            prompt_version_id=prompt_invocation.prompt_version_id,
            output=result.output,
        )
        prompt_invocation = prompt_invocation.model_copy(
            update={"provider_invocation_id": invocation.id, "updated_at": utcnow()}
        )
        self.repository.prompt_invocations[prompt_invocation.id] = prompt_invocation
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.creative_intent,
            result.output,
            "CreativeIntentArtifact.v1",
        )
        return NodeOutput(artifacts=[artifact], provider_invocation_ids=[invocation.id])

    def _tts(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        provider_profile_id = state.request.voice.provider_profile_id or "sandbox.tts.default"
        invocation, result = self.provider_gateway.invoke(
            ProviderCall(
                case_id=run.case_id,
                run_id=run.id,
                node_run_id=node_run.id,
                provider_profile_id=provider_profile_id,
                capability_id="tts",
                input={"text": state.request.script, "voice_id": state.request.voice.voice_id or "voice_sandbox"},
            )
        )
        if result is None or invocation.error:
            raise NodeExecutionError(
                invocation.error.code if invocation.error else ErrorCode.provider_remote_failed,
                invocation.error.message if invocation.error else "TTS provider failed.",
                retryable=True,
            )
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.audio_tts,
            result.output,
            "TtsAudioArtifact.v1",
            uri=str(result.output.get("audio_uri")),
        )
        return NodeOutput(artifacts=[artifact], provider_invocation_ids=[invocation.id])

    def _material_pack_planning(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        request = state.request
        assets = list(self.repository.media_assets.values())
        portrait = [
            asset.id
            for asset in assets
            if asset.usable
            and asset.kind == "portrait"
            and (asset.case_id in {None, request.case_id})
            and (not request.portrait.asset_ids or asset.id in request.portrait.asset_ids)
        ]
        broll = [
            asset.id
            for asset in assets
            if asset.usable
            and asset.kind == "broll"
            and (asset.case_id in {None, request.case_id})
            and (not request.broll.asset_ids or asset.id in request.broll.asset_ids)
        ]
        bgm = [
            asset.id
            for asset in assets
            if asset.usable and asset.kind == "bgm" and asset.case_id in {None, request.case_id}
        ]
        fonts = [
            asset.id
            for asset in assets
            if asset.usable and asset.kind == "font" and asset.case_id in {None, request.case_id}
        ]
        payload = {
            "portrait_candidates": portrait,
            "broll_candidates": broll,
            "bgm_candidates": bgm,
            "font_candidates": fonts,
            "diagnostics": {
                "portrait_missing": not bool(portrait),
                "broll_missing": request.broll.enabled and not bool(broll),
                "bgm_missing": request.bgm.enabled and not bool(bgm),
            },
            "reservation_ids": [new_id("reserve")],
        }
        return NodeOutput(
            artifacts=[
                self._artifact(
                    run,
                    node_run,
                    ArtifactKind.plan_material_pack,
                    payload,
                    "MaterialPackPlanArtifact.v1",
                )
            ]
        )

    def _narration_alignment(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        tts = state.require(ArtifactKind.audio_tts)
        duration = float((tts.payload or {}).get("duration_sec", 1))
        parts = [part.strip() for part in state.request.script.replace("。", ".").split(".") if part.strip()]
        if not parts:
            parts = [state.request.script]
        unit_duration = duration / len(parts)
        units = [
            {"index": index, "text": text, "start_sec": round(index * unit_duration, 3), "end_sec": round((index + 1) * unit_duration, 3)}
            for index, text in enumerate(parts)
        ]
        alignment = {"duration_sec": duration, "source": "tts", "units": units}
        return NodeOutput(
            artifacts=[
                self._artifact(run, node_run, ArtifactKind.audio_alignment, alignment, "AlignmentArtifact.v1"),
                self._artifact(run, node_run, ArtifactKind.narration_units, {"units": units}, "NarrationUnitsArtifact.v1"),
            ]
        )

    def _portrait_planning(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        material = state.require(ArtifactKind.plan_material_pack).payload or {}
        narration = state.require(ArtifactKind.narration_units).payload or {}
        portraits = list(material.get("portrait_candidates", []))
        if state.request.portrait.required and not portraits:
            raise NodeExecutionError(
                ErrorCode.material_insufficient_portrait,
                "Portrait main track cannot cover the full audio.",
            )
        duration = max([float(unit.get("end_sec", 0)) for unit in narration.get("units", [])] or [1])
        payload = {
            "asset_id": portraits[0] if portraits else None,
            "segments": [{"asset_id": portraits[0] if portraits else None, "start_sec": 0, "end_sec": duration}],
            "duration_sec": duration,
        }
        return NodeOutput(
            artifacts=[
                self._artifact(run, node_run, ArtifactKind.plan_portrait, payload, "PortraitPlanArtifact.v1")
            ]
        )

    def _broll_planning(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        material = state.require(ArtifactKind.plan_material_pack).payload or {}
        broll = list(material.get("broll_candidates", []))
        if state.request.broll.enabled and not broll:
            artifact = self._artifact(
                run,
                node_run,
                ArtifactKind.plan_broll,
                {"segments": [], "skipped_reason": DegradationCode.broll_skipped_no_material.value},
                "BrollPlanArtifact.v1",
            )
            return NodeOutput(
                status=NodeStatus.degraded,
                artifacts=[artifact],
                degradations=[DegradationCode.broll_skipped_no_material],
            )
        segments = [
            {"asset_id": asset_id, "start_sec": index * 3, "end_sec": index * 3 + 2}
            for index, asset_id in enumerate(broll[: state.request.broll.max_inserts])
        ]
        return NodeOutput(
            artifacts=[
                self._artifact(
                    run,
                    node_run,
                    ArtifactKind.plan_broll,
                    {"segments": segments, "skipped_reason": None},
                    "BrollPlanArtifact.v1",
                )
            ]
        )

    def _style_planning(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        material = state.require(ArtifactKind.plan_material_pack).payload or {}
        bgm_candidates = list(material.get("bgm_candidates", []))
        font_candidates = list(material.get("font_candidates", []))
        degradations: list[DegradationCode] = []
        warnings: list[WarningCode] = []
        bgm_asset_id = state.request.bgm.asset_id or (bgm_candidates[0] if bgm_candidates else None)
        if state.request.bgm.enabled and not bgm_asset_id:
            degradations.append(DegradationCode.bgm_skipped_library_unannotated)
            warnings.append(WarningCode.bgm_library_unannotated)
        font_asset_id = font_candidates[0] if font_candidates else "case_default_font"
        if not font_candidates:
            warnings.append(WarningCode.font_default_used)
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.plan_style,
            {
                "font_asset_id": font_asset_id,
                "bgm_asset_id": bgm_asset_id,
                "subtitle_enabled": state.request.subtitles.enabled,
            },
            "StylePlanArtifact.v1",
        )
        return NodeOutput(
            status=NodeStatus.degraded if degradations else NodeStatus.succeeded,
            artifacts=[artifact],
            warnings=warnings,
            degradations=degradations,
        )

    def _timeline_planning(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        portrait = state.require(ArtifactKind.plan_portrait).payload or {}
        broll = state.require(ArtifactKind.plan_broll).payload or {}
        duration = float(portrait.get("duration_sec", 0))
        if duration <= 0:
            raise NodeExecutionError(ErrorCode.render_invalid_timeline, "Timeline duration is invalid.")
        for segment in broll.get("segments", []):
            if float(segment["start_sec"]) < 0 or float(segment["end_sec"]) <= float(segment["start_sec"]):
                raise NodeExecutionError(ErrorCode.render_invalid_timeline, "B-roll segment is invalid.")
        timeline = {
            "fps": 30,
            "duration_sec": duration,
            "tracks": {"portrait": portrait.get("segments", []), "broll": broll.get("segments", [])},
            "validation": {"overlap": False, "negative_duration": False, "out_of_bounds": False},
        }
        render_plan = {"width": state.request.output.width, "height": state.request.output.height, "fps": 30}
        return NodeOutput(
            artifacts=[
                self._artifact(run, node_run, ArtifactKind.plan_timeline, timeline, "TimelinePlanArtifact.v1"),
                self._artifact(run, node_run, ArtifactKind.plan_render, render_plan, "RenderPlanArtifact.v1"),
            ]
        )

    def _portrait_track_build(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        portrait = state.require(ArtifactKind.plan_portrait).payload or {}
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.video_portrait_track,
            {"video_uri": f"sandbox://video/portrait-track/{run.id}.mp4", "duration_sec": portrait.get("duration_sec", 0)},
            "PortraitTrackArtifact.v1",
            uri=f"sandbox://video/portrait-track/{run.id}.mp4",
        )
        return NodeOutput(artifacts=[artifact])

    def _lipsync(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        portrait = state.require(ArtifactKind.video_portrait_track)
        audio = state.require(ArtifactKind.audio_tts)
        duration = float((audio.payload or {}).get("duration_sec", 0))
        if not state.request.lipsync.enabled:
            artifact = self._artifact(
                run,
                node_run,
                ArtifactKind.video_lipsync,
                portrait.payload,
                "LipSyncVideoArtifact.v1",
                uri=portrait.uri,
            )
            return NodeOutput(status=NodeStatus.skipped, artifacts=[artifact])
        invocation, result = self.provider_gateway.invoke(
            ProviderCall(
                case_id=run.case_id,
                run_id=run.id,
                node_run_id=node_run.id,
                provider_profile_id=state.request.lipsync.provider_profile_id,
                capability_id="lipsync",
                input={"portrait_uri": portrait.uri or "", "audio_uri": audio.uri or "", "duration_sec": duration},
            )
        )
        if result is None or invocation.error:
            raise NodeExecutionError(
                invocation.error.code if invocation.error else ErrorCode.provider_remote_failed,
                invocation.error.message if invocation.error else "LipSync provider failed.",
                retryable=True,
            )
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.video_lipsync,
            result.output,
            "LipSyncVideoArtifact.v1",
            uri=str(result.output.get("video_uri")),
        )
        return NodeOutput(artifacts=[artifact], provider_invocation_ids=[invocation.id])

    def _render_final_timeline(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        lipsync = state.require(ArtifactKind.video_lipsync)
        render_plan = state.require(ArtifactKind.plan_render).payload or {}
        artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.video_rendered,
            {
                "video_uri": f"sandbox://video/rendered/{run.id}.mp4",
                "source_lipsync_artifact_id": lipsync.id,
                "render_plan": render_plan,
            },
            "RenderedVideoArtifact.v1",
            uri=f"sandbox://video/rendered/{run.id}.mp4",
        )
        return NodeOutput(artifacts=[artifact])

    def _subtitle_and_bgm_mix(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        rendered = state.require(ArtifactKind.video_rendered)
        style = state.require(ArtifactKind.plan_style).payload or {}
        final = self._artifact(
            run,
            node_run,
            ArtifactKind.video_final,
            {
                "video_uri": f"sandbox://video/final/{run.id}.mp4",
                "source_rendered_artifact_id": rendered.id,
                "bgm_asset_id": style.get("bgm_asset_id"),
                "subtitles_enabled": state.request.subtitles.enabled,
            },
            "FinalVideoArtifact.v1",
            uri=f"sandbox://video/final/{run.id}.mp4",
        )
        subtitle = self._artifact(
            run,
            node_run,
            ArtifactKind.subtitle_ass,
            {"subtitle_uri": f"sandbox://subtitle/{run.id}.ass"},
            "SubtitleAssArtifact.v1",
            uri=f"sandbox://subtitle/{run.id}.ass",
        )
        if not state.request.subtitles.enabled:
            return NodeOutput(status=NodeStatus.skipped, artifacts=[final, subtitle])
        return NodeOutput(artifacts=[final, subtitle])

    def _export_finished_video(
        self, run: WorkflowRun, node_run: NodeRun, state: RunState
    ) -> NodeOutput:
        final = state.require(ArtifactKind.video_final)
        timeline = state.require(ArtifactKind.plan_timeline)
        style = state.require(ArtifactKind.plan_style)
        script = ScriptVersion(
            id=state.request.script_version_id or new_id("script"),
            case_id=state.request.case_id,
            title=state.request.title or "Untitled script",
            script=state.request.script,
            creative_intent_artifact_id=state.artifacts.get(ArtifactKind.creative_intent).id
            if ArtifactKind.creative_intent in state.artifacts
            else None,
        )
        self.repository.scripts[script.id] = script
        video_artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.video_finished,
            {"video_uri": final.uri, "source_final_artifact_id": final.id},
            "FinishedVideoArtifact.v1",
            uri=final.uri,
        )
        cover_artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.cover_image,
            {"image_uri": f"sandbox://cover/frame/{run.id}.png", "source": "frame"},
            "CoverImageArtifact.v1",
            uri=f"sandbox://cover/frame/{run.id}.png",
        )
        finished = FinishedVideo(
            id=new_id("fv"),
            case_id=state.request.case_id,
            run_id=run.id,
            title=state.request.title or script.title,
            video_artifact=self.repository.artifact_ref(video_artifact.id),
            cover_artifact=self.repository.artifact_ref(cover_artifact.id),
            subtitle_artifact=self.repository.artifact_ref(state.require(ArtifactKind.subtitle_ass).id),
            duration_sec=float((timeline.payload or {}).get("duration_sec", 0)),
        )
        self.repository.finished_videos[finished.id] = finished
        video_version = VideoVersion(
            id=new_id("vv"),
            case_id=state.request.case_id,
            script_version_id=script.id,
            finished_video_id=finished.id,
            timeline_plan_artifact_id=timeline.id,
            style_plan_artifact_id=style.id,
        )
        self.repository.video_versions[video_version.id] = video_version
        package = self.repository.create_publish_package_from_finished_video(
            finished,
            title=finished.title,
            description=state.request.publish_content,
        )
        package_artifact = self._artifact(
            run,
            node_run,
            ArtifactKind.publish_package,
            package.model_dump(mode="json"),
            "PublishPackageArtifact.v1",
        )
        return NodeOutput(artifacts=[video_artifact, cover_artifact, package_artifact])

    def _finalize_run_report(self, run: WorkflowRun, node_run: NodeRun, state: RunState) -> NodeOutput:
        public_artifact, debug_artifact = self._write_report(run, state, failed=False, node_run=node_run)
        return NodeOutput(artifacts=[public_artifact, debug_artifact])

    def _write_report(
        self,
        run: WorkflowRun,
        state: RunState,
        *,
        failed: bool,
        node_run: NodeRun | None = None,
    ) -> tuple[Artifact, Artifact]:
        node_runs = self.repository.node_runs.get(run.id, [])
        public = RunPublicReportArtifact(
            run_id=run.id,
            status=RunStatus.failed if failed else (RunStatus.degraded if state.degradations else RunStatus.succeeded),
            summary="Run failed." if failed else "Run completed.",
            node_statuses={node.node_id: node.status for node in node_runs},
            warnings=state.warnings,
            degradations=state.degradations,
        )
        debug = RunDebugReportArtifact(
            **public.model_dump(),
            artifact_ids=list(self.repository.artifacts.keys()),
            provider_invocation_ids=state.provider_invocation_ids,
            node_errors=[node.error for node in node_runs if node.error is not None],
        )
        public_artifact = self.repository.create_artifact(
            kind=ArtifactKind.run_report_public,
            payload_schema="RunPublicReportArtifact.v1",
            payload=public.model_dump(mode="json"),
            case_id=run.case_id,
            run_id=run.id,
            node_run_id=node_run.id if node_run else None,
        )
        debug_artifact = self.repository.create_artifact(
            kind=ArtifactKind.run_report_debug,
            payload_schema="RunDebugReportArtifact.v1",
            payload=debug.model_dump(mode="json"),
            case_id=run.case_id,
            run_id=run.id,
            node_run_id=node_run.id if node_run else None,
        )
        self.repository.runs[run.id] = self.repository.runs[run.id].model_copy(
            update={
                "public_report_artifact_id": public_artifact.id,
                "debug_report_artifact_id": debug_artifact.id,
                "updated_at": utcnow(),
            }
        )
        return public_artifact, debug_artifact


_WORKFLOW = DigitalHumanWorkflow(
    get_repository(),
    get_provider_gateway(),
    get_prompt_registry(),
)


def get_digital_human_workflow() -> DigitalHumanWorkflow:
    return _WORKFLOW
