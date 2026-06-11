from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue


T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ErrorCode(str, Enum):
    validation_missing_case = "validation.missing_case"
    validation_missing_voice = "validation.missing_voice"
    validation_missing_script = "validation.missing_script"
    validation_invalid_options = "validation.invalid_options"
    auth_unauthorized = "auth.unauthorized"
    auth_forbidden = "auth.forbidden"
    auth_invalid_credentials = "auth.invalid_credentials"
    auth_registration_closed = "auth.registration_closed"
    auth_user_disabled = "auth.user_disabled"
    upload_invalid_state = "upload.invalid_state"
    upload_expired = "upload.expired"
    upload_size_mismatch = "upload.size_mismatch"
    upload_sha256_mismatch = "upload.sha256_mismatch"
    upload_unsupported_type = "upload.unsupported_type"
    material_insufficient_portrait = "material.insufficient.portrait"
    material_insufficient_broll = "material.insufficient.broll"
    material_annotation_failed = "material.annotation_failed"
    prompt_render_error = "prompt.render_error"
    prompt_output_invalid = "prompt.output_invalid"
    prompt_version_not_published = "prompt.version_not_published"
    provider_unsupported_option = "provider.unsupported_option"
    provider_quota_exceeded = "provider.quota_exceeded"
    provider_timeout = "provider.timeout"
    provider_remote_failed = "provider.remote_failed"
    provider_auth_failed = "provider.auth_failed"
    provider_cost_unpriced = "provider.cost_unpriced"
    artifact_missing = "artifact.missing"
    artifact_integrity_failed = "artifact.integrity_failed"
    artifact_schema_mismatch = "artifact.schema_mismatch"
    workflow_invalid_transition = "workflow.invalid_transition"
    workflow_cancelled = "workflow.cancelled"
    workflow_resume_not_allowed = "workflow.resume_not_allowed"
    render_invalid_timeline = "render.invalid_timeline"
    render_failed = "render.failed"
    render_subtitle_failed = "render.subtitle_failed"
    publish_failed = "publish.failed"
    import_failed = "import.failed"
    idempotency_conflict = "idempotency.conflict"


class WarningCode(str, Enum):
    cost_unpriced = "cost.unpriced"
    cover_frame_fallback = "cover.frame_fallback"
    broll_skipped_no_material = "broll.skipped_no_material"
    bgm_skipped_library_unannotated = "bgm.skipped_library_unannotated"
    font_default_used = "font.default_used"
    timestamp_estimated = "timestamp.estimated"
    platform_metrics_waiting = "platform.metrics_waiting"


class DegradationCode(str, Enum):
    broll_skipped_no_material = "broll.skipped_no_material"
    bgm_skipped_library_unannotated = "bgm.skipped_library_unannotated"
    font_default_used = "font.default_used"
    cover_frame_fallback = "cover.frame_fallback"


class JobStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    archived = "archived"


class RunStatus(str, Enum):
    created = "created"
    admitted = "admitted"
    running = "running"
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class NodeStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    degraded = "degraded"
    cancelled = "cancelled"


class ProviderStatus(str, Enum):
    prepared = "prepared"
    submitted = "submitted"
    polling = "polling"
    succeeded = "succeeded"
    failed = "failed"
    timed_out = "timed_out"
    cancelled = "cancelled"


class JobType(str, Enum):
    digital_human_video = "digital_human_video"
    case_agent_run = "case_agent_run"
    publish_batch = "publish_batch"
    annotation_batch = "annotation_batch"


class ArtifactKind(str, Enum):
    uploaded_file = "uploaded.file"
    validated_production_spec = "validated.production_spec"
    case_context = "case.context"
    creative_intent = "creative.intent"
    audio_tts = "audio.tts"
    audio_alignment_raw = "audio.alignment.raw"
    audio_alignment = "audio.alignment"
    narration_units = "narration.units"
    plan_material_pack = "plan.material_pack"
    plan_portrait = "plan.portrait"
    plan_broll = "plan.broll"
    plan_style = "plan.style"
    plan_timeline = "plan.timeline"
    plan_render = "plan.render"
    video_portrait_track = "video.portrait_track"
    video_lipsync = "video.lipsync"
    video_rendered = "video.rendered"
    video_final = "video.final"
    video_finished = "video.finished"
    subtitle_ass = "subtitle.ass"
    cover_image = "cover.image"
    publish_package = "publish.package"
    run_report_public = "run.report.public"
    run_report_debug = "run.report.debug"
    case_reflection = "case.reflection"
    editor_handoff = "editor.handoff"
    jianying_draft = "jianying.draft"
    import_mapping = "import.mapping"


class UploadSessionStatus(str, Enum):
    prepared = "prepared"
    uploading = "uploading"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


UploadStatus = UploadSessionStatus


class UserRole(str, Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class Money(ContractModel):
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    amount_micro: int | None = None


def zero_money(currency: str = "CNY") -> Money:
    return Money(amount=Decimal("0"), currency=currency, amount_micro=0)


class EntityMeta(ContractModel):
    id: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    schema_version: str = "v1"


class BaseListQuery(ContractModel):
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None


class OkResponse(ContractModel):
    ok: bool = True
    request_id: str


class PageResponse(ContractModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total_hint: int | None = None
    request_id: str


class SignedUrlResponse(ContractModel):
    url: str
    expires_at: datetime
    request_id: str


class EventStreamTokenResponse(ContractModel):
    stream_url: str
    token: str
    expires_at: datetime
    request_id: str


class NodeError(ContractModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    severity: Literal["info", "warning", "error", "fatal"] = "error"
    details: dict[str, JsonValue] = Field(default_factory=dict)
    request_id: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    node_run_id: str | None = None


class ErrorEnvelope(ContractModel):
    error: NodeError


class ArtifactRef(ContractModel):
    artifact_id: str
    kind: ArtifactKind
    schema_version: str = "v1"
    sha256: str | None = None


class MediaInfo(ContractModel):
    mime_type: str | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


class Artifact(EntityMeta):
    case_id: str | None = None
    run_id: str | None = None
    node_run_id: str | None = None
    kind: ArtifactKind
    uri: str | None = None
    sha256: str | None = None
    media_info: MediaInfo | None = None
    payload_schema: str
    payload: JsonValue | None = None
    created_by_node_run_id: str | None = None


class ProviderError(ContractModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    raw_error_artifact_id: str | None = None


class UsageMeterRecord(EntityMeta):
    provider_invocation_id: str
    provider_id: str
    model_id: str
    capability_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    audio_seconds: float = 0
    video_seconds: float = 0
    image_count: int = 0
    provider_credits: Decimal | None = None
    raw_usage: dict[str, Any] = Field(default_factory=dict)


class ProviderInvocation(EntityMeta):
    case_id: str | None = None
    run_id: str | None = None
    node_run_id: str | None = None
    provider_id: str
    model_id: str
    provider_profile_id: str
    capability_id: str
    prompt_version_id: str | None = None
    status: ProviderStatus
    usage: UsageMeterRecord | None = None
    price_item_id: str | None = None
    billing_status: Literal["estimated", "reconciled", "unpriced", "ignored"] = "estimated"
    duration_ms: int = 0
    retry_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: Money | None = None
    actual_cost: Money | None = None
    request_artifact_id: str | None = None
    response_artifact_id: str | None = None
    external_job_id: str | None = None
    error: ProviderError | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class RetryPolicy(ContractModel):
    max_attempts: int = 3
    initial_interval_seconds: float = 1
    backoff_coefficient: float = 2
    max_interval_seconds: float = 30


class ResumePolicy(ContractModel):
    can_reuse_artifacts: bool = True
    side_effect_resume_requires_idempotency_key: bool = True


class WorkflowEdge(ContractModel):
    from_node_id: str
    to_node_id: str
    condition: str | None = None


class NodeSpec(ContractModel):
    node_id: str
    node_version: str = "v1"
    input_schema: str
    output_artifact_kinds: list[ArtifactKind]
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    resume_policy: ResumePolicy = Field(default_factory=ResumePolicy)
    side_effects: list[
        Literal["provider_call", "ledger_commit", "external_upload", "publish_attempt"]
    ] = Field(default_factory=list)


class WorkflowTemplate(ContractModel):
    workflow_template_id: str
    version: str
    nodes: list[NodeSpec]
    edges: list[WorkflowEdge] = Field(default_factory=list)


class VoiceOptions(ContractModel):
    voice_id: str | None = None
    provider_profile_id: str | None = None
    speed: float = Field(1.0, gt=0, le=3)


class PortraitOptions(ContractModel):
    required: bool = True
    asset_ids: list[str] = Field(default_factory=list)


class BrollOptions(ContractModel):
    enabled: bool = False
    max_inserts: int = Field(3, ge=0, le=30)
    asset_ids: list[str] = Field(default_factory=list)


class LipSyncOptions(ContractModel):
    enabled: bool = True
    provider_profile_id: str = "runninghub.heygem.default"
    ref_image_artifact_id: str | None = None
    options: dict[str, JsonValue] = Field(default_factory=dict)


class SubtitleOptions(ContractModel):
    enabled: bool = True
    style: dict[str, JsonValue] = Field(default_factory=dict)


class BgmOptions(ContractModel):
    enabled: bool = False
    asset_id: str | None = None
    volume: float = Field(0.2, ge=0, le=1)


class CoverOptions(ContractModel):
    mode: Literal["ai", "frame", "upload"] = "frame"
    upload_artifact_id: str | None = None


class OutputOptions(ContractModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    format: Literal["mp4"] = "mp4"


class StrictnessOptions(ContractModel):
    strict_alignment: bool = False
    strict_cost_pricing: bool = False


class DigitalHumanVideoRequest(ContractModel):
    case_id: str
    script: str
    title: str | None = None
    publish_content: str = ""
    script_version_id: str | None = None
    creative_intent_ref: ArtifactRef | None = None
    workflow_template_id: str = "digital_human_v2"
    voice: VoiceOptions = Field(default_factory=VoiceOptions)
    portrait: PortraitOptions = Field(default_factory=PortraitOptions)
    broll: BrollOptions = Field(default_factory=BrollOptions)
    lipsync: LipSyncOptions = Field(default_factory=LipSyncOptions)
    subtitles: SubtitleOptions = Field(default_factory=SubtitleOptions)
    bgm: BgmOptions = Field(default_factory=BgmOptions)
    cover: CoverOptions = Field(default_factory=CoverOptions)
    output: OutputOptions = Field(default_factory=OutputOptions)
    strictness: StrictnessOptions = Field(default_factory=StrictnessOptions)


class CaseAgentRunRequest(ContractModel):
    case_id: str
    goal: Literal["brief", "script_draft", "memory_proposal"]
    source_binding_ids: list[str] = Field(default_factory=list)


class PublishBatchRequest(ContractModel):
    publish_package_ids: list[str]
    platform_targets: list[str]


class AnnotationBatchRequest(ContractModel):
    asset_ids: list[str]
    provider_profile_id: str | None = None


class Job(EntityMeta):
    type: JobType
    status: JobStatus = JobStatus.draft
    case_id: str | None = None
    created_by_user_id: str | None = None
    request: (
        DigitalHumanVideoRequest | CaseAgentRunRequest | PublishBatchRequest | AnnotationBatchRequest
    )
    current_run_id: str | None = None


class WorkflowRun(EntityMeta):
    job_id: str
    case_id: str | None = None
    workflow_template_id: str
    workflow_version: str
    status: RunStatus = RunStatus.created
    run_attempt: int = 1
    resume_from_run_id: str | None = None
    retry_from_run_id: str | None = None
    public_report_artifact_id: str | None = None
    debug_report_artifact_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class NodeRun(EntityMeta):
    run_id: str
    node_id: str
    node_version: str
    status: NodeStatus
    input_manifest_hash: str | None = None
    output_artifact_ids: list[str] = Field(default_factory=list)
    provider_invocation_ids: list[str] = Field(default_factory=list)
    error: NodeError | None = None
    warnings: list[WarningCode] = Field(default_factory=list)
    degradations: list[DegradationCode] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ValidatedProductionSpec(ContractModel):
    request: DigitalHumanVideoRequest
    workflow_template_id: str
    workflow_version: str
    compatible: bool = True


class AuthUser(EntityMeta):
    email: str
    display_name: str
    role: UserRole = UserRole.viewer
    disabled: bool = False


class SessionInfo(ContractModel):
    user: AuthUser
    expires_at: datetime
    request_id: str


class LoginRequest(ContractModel):
    email: str
    password: str


class RegisterRequest(LoginRequest):
    display_name: str
    registration_code: str | None = None


class AuthResponse(ContractModel):
    user: AuthUser
    session: SessionInfo
    request_id: str


class ChangePasswordRequest(ContractModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserListQuery(BaseListQuery):
    role: UserRole | None = None
    disabled: bool | None = None


class AdminCreateUserRequest(RegisterRequest):
    role: UserRole = UserRole.viewer


class AdminUpdateUserRequest(ContractModel):
    display_name: str | None = None
    role: UserRole | None = None
    disabled: bool | None = None


class RegistrationCodeQuery(BaseListQuery):
    status: Literal["active", "disabled", "expired"] | None = None


class RegistrationCodePreview(ContractModel):
    id: str
    role: UserRole
    status: Literal["active", "disabled", "expired"]
    max_uses: int | None = None
    used_count: int
    expires_at: datetime | None = None
    created_at: datetime


class CreateRegistrationCodeRequest(ContractModel):
    role: UserRole
    max_uses: int | None = None
    expires_at: datetime | None = None


class UpdateRegistrationCodeRequest(ContractModel):
    status: Literal["active", "disabled", "expired"] | None = None
    expires_at: datetime | None = None


class UpdateMeRequest(ContractModel):
    display_name: str | None = None


class PrepareUploadRequest(ContractModel):
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    sha256: str | None = None
    purpose: Literal["media", "voice", "finished_video", "import", "cover"] = "media"


class UploadSession(EntityMeta):
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    status: UploadStatus = UploadStatus.prepared
    purpose: str = "media"
    upload_url: str | None = None
    object_uri: str | None = None
    expires_at: datetime = Field(default_factory=lambda: utcnow() + timedelta(hours=1))


class CompleteUploadRequest(ContractModel):
    upload_session_id: str
    size_bytes: int
    sha256: str | None = None


class CompleteUploadResponse(ContractModel):
    upload_session: UploadSession
    artifact: ArtifactRef | None = None
    request_id: str


class SecretQuery(BaseListQuery):
    provider_id: str | None = None
    environment: str | None = None
    status: str | None = None


class CreateSecretRequest(ContractModel):
    provider_id: str
    environment: Literal["local", "dev", "staging", "prod"]
    name: str
    value: str


class RotateSecretRequest(ContractModel):
    value: str
    reason: str


class DisableSecretRequest(ContractModel):
    reason: str


class SecretPreview(EntityMeta):
    provider_id: str
    environment: str
    name: str
    status: Literal["active", "disabled"] = "active"
    masked_value: str = "********"


class CaseListQuery(BaseListQuery):
    search: str | None = None
    owner_user_id: str | None = None


class CreateCaseRequest(ContractModel):
    name: str
    description: str | None = None
    industry: str | None = None
    product: str | None = None
    target_audience: str | None = None


class PatchCaseRequest(ContractModel):
    name: str | None = None
    description: str | None = None
    product: str | None = None
    target_audience: str | None = None


class CaseListItem(EntityMeta):
    name: str
    owner_user_id: str | None = None
    active_memory_count: int = 0


class CaseDetail(CaseListItem):
    description: str | None = None
    industry: str | None = None
    product: str | None = None
    target_audience: str | None = None


CreateDigitalHumanVideoJobRequest = DigitalHumanVideoRequest


class CreateRunRequest(ContractModel):
    mode: Literal["new", "retry", "resume"] = "new"
    reason: str | None = None


class CancelRunRequest(ContractModel):
    reason: str | None = None
    force: bool = False


class RetryRunRequest(ContractModel):
    reason: str | None = None


class ResumeRunRequest(ContractModel):
    reason: str | None = None
    reuse_valid_artifacts: bool = True


class WorkflowRunResponse(ContractModel):
    run: WorkflowRun
    request_id: str


RetryRunResponse = WorkflowRunResponse
ResumeRunResponse = WorkflowRunResponse


class CreateJobResponse(ContractModel):
    job: Job
    initial_run: WorkflowRun | None
    request_id: str


class JobDetailResponse(ContractModel):
    job: Job
    runs: list[WorkflowRun]
    latest_report_artifact_id: str | None = None
    request_id: str = "req_local"


class RunDetailResponse(ContractModel):
    run: WorkflowRun
    node_runs: list[NodeRun]
    artifacts: list[ArtifactRef]
    request_id: str = "req_local"


class RunActionResponse(ContractModel):
    run: WorkflowRun
    accepted: bool
    request_id: str = "req_local"


class RunPublicReportArtifact(ContractModel):
    run_id: str
    status: RunStatus
    summary: str
    node_statuses: dict[str, NodeStatus]
    warnings: list[WarningCode] = Field(default_factory=list)
    degradations: list[DegradationCode] = Field(default_factory=list)


class RunDebugReportArtifact(RunPublicReportArtifact):
    artifact_ids: list[str] = Field(default_factory=list)
    provider_invocation_ids: list[str] = Field(default_factory=list)
    node_errors: list[NodeError] = Field(default_factory=list)


class RunReportResponse(ContractModel):
    public_report: RunPublicReportArtifact
    debug_report: RunDebugReportArtifact | None = None
    request_id: str = "req_local"


class RunArtifactsResponse(ContractModel):
    run_id: str
    artifacts: list[ArtifactRef]
    request_id: str


class RunEventsQuery(BaseListQuery):
    since_id: str | None = None


class MediaAssetRecord(EntityMeta):
    case_id: str | None = None
    title: str
    kind: Literal["portrait", "broll", "bgm", "font", "voice", "video", "image", "other"]
    source_artifact_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    annotation_status: Literal["pending", "annotated", "annotation_failed"] = "pending"
    usable: bool = True


class MediaAssetQuery(BaseListQuery):
    case_id: str | None = None
    kind: str | None = None
    annotation_status: str | None = None


class CreateMediaAssetFromUploadRequest(ContractModel):
    upload_session_id: str
    case_id: str | None = None
    title: str
    tags: list[str] = Field(default_factory=list)
    kind: Literal["portrait", "broll", "bgm", "font", "voice", "video", "image", "other"] = "other"


class MediaAssetCard(ContractModel):
    asset: MediaAssetRecord
    preview_url: str | None = None
    latest_annotation_id: str | None = None
    badges: list[str] = Field(default_factory=list)


class MediaAssetDetail(ContractModel):
    asset: MediaAssetRecord
    preview_url: str | None = None
    latest_annotation_id: str | None = None


class AnnotationPatch(ContractModel):
    operations: list[dict[str, JsonValue]] = Field(default_factory=list)


class PatchAnnotationRequest(ContractModel):
    etag: str
    patch: AnnotationPatch


class RerunAnnotationRequest(ContractModel):
    provider_profile_id: str | None = None
    force: bool = False


class AnnotationRunResponse(ContractModel):
    asset_id: str
    run_id: str | None
    status: Literal["queued", "running", "completed", "failed"]


class AnnotationEditorVm(ContractModel):
    asset: MediaAssetRecord
    etag: str
    canonical: dict[str, JsonValue]
    projection: dict[str, JsonValue]
    editable_paths: list[str] = Field(default_factory=list)


class VoiceProfile(EntityMeta):
    display_name: str
    source: Literal["builtin", "cloned", "designed"]
    provider_profile_id: str | None = None
    preview_artifact_id: str | None = None
    enabled: bool = True


class VoiceQuery(BaseListQuery):
    source: str | None = None
    enabled: bool | None = None


class CloneVoiceRequest(ContractModel):
    display_name: str
    reference_upload_session_id: str
    provider_profile_id: str | None = None


class DesignVoiceRequest(ContractModel):
    display_name: str
    prompt: str
    provider_profile_id: str | None = None


class VoicePreviewRequest(ContractModel):
    text: str
    provider_profile_id: str | None = None


class VoicePreviewResponse(ContractModel):
    voice_id: str
    audio_artifact: ArtifactRef
    duration_sec: float


class PatchVoiceRequest(ContractModel):
    display_name: str | None = None
    enabled: bool | None = None


class PromptSchemaRef(ContractModel):
    schema_id: str
    schema_version: str = "v1"


class PromptTemplate(EntityMeta):
    name: str
    purpose: str
    variables_schema_ref: PromptSchemaRef
    output_schema_ref: PromptSchemaRef
    status: Literal["draft", "active", "deprecated"] = "draft"


class PromptVersion(EntityMeta):
    prompt_template_id: str
    content: str
    status: Literal["draft", "reviewing", "approved", "published", "deprecated", "rolled_back"] = (
        "draft"
    )
    changelog: str | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None


class PromptBinding(EntityMeta):
    prompt_template_id: str
    prompt_version_id: str
    case_id: str | None = None
    node_id: str | None = None
    provider_profile_id: str | None = None
    priority: int = 100
    enabled: bool = True


class PromptInvocation(EntityMeta):
    prompt_template_id: str
    prompt_version_id: str
    case_id: str | None = None
    run_id: str | None = None
    node_run_id: str | None = None
    provider_invocation_id: str | None = None
    variables_artifact_id: str | None = None
    output_artifact_id: str | None = None
    status: Literal["succeeded", "failed"] = "succeeded"


class PromptTemplateQuery(BaseListQuery):
    status: str | None = None
    purpose: str | None = None


class PromptTemplateView(ContractModel):
    template: PromptTemplate
    published_version: PromptVersion | None = None


class PromptVersionView(ContractModel):
    version: PromptVersion
    template: PromptTemplate | None = None


class PromptBindingQuery(BaseListQuery):
    case_id: str | None = None
    node_id: str | None = None


class PromptBindingView(ContractModel):
    binding: PromptBinding
    resolved_version: PromptVersion | None = None


class CreatePromptTemplateRequest(ContractModel):
    name: str
    purpose: str
    variables_schema_ref: PromptSchemaRef
    output_schema_ref: PromptSchemaRef


class CreatePromptVersionRequest(ContractModel):
    content: str
    changelog: str | None = None


class ApprovePromptVersionRequest(ContractModel):
    reason: str


class PublishPromptVersionRequest(ContractModel):
    reason: str


class RollbackPromptRequest(ContractModel):
    target_version_id: str
    reason: str


class CreatePromptBindingRequest(ContractModel):
    prompt_template_id: str
    prompt_version_id: str
    case_id: str | None = None
    node_id: str | None = None
    priority: int


class PatchPromptBindingRequest(ContractModel):
    prompt_version_id: str | None = None
    enabled: bool | None = None
    priority: int | None = None


class PromptExperimentScope(ContractModel):
    case_id: str | None = None
    node_id: str | None = None


class PromptExperiment(EntityMeta):
    prompt_template_id: str
    variants: list[str]
    traffic_split: dict[str, float]
    scope: PromptExperimentScope
    status: Literal["draft", "running", "stopped", "completed"] = "draft"
    start_at: datetime | None = None
    end_at: datetime | None = None


class PromptExperimentQuery(BaseListQuery):
    prompt_template_id: str | None = None
    status: str | None = None


class CreatePromptExperimentRequest(ContractModel):
    prompt_template_id: str
    variants: list[str]
    traffic_split: dict[str, float]
    scope: PromptExperimentScope
    start_at: datetime | None = None
    end_at: datetime | None = None


class PatchPromptExperimentRequest(ContractModel):
    status: Literal["draft", "running", "stopped", "completed"] | None = None
    traffic_split: dict[str, float] | None = None
    end_at: datetime | None = None


class ProviderOptionsSchemaRef(ContractModel):
    schema_id: str
    schema_version: str = "v1"


class ProviderCapability(EntityMeta):
    provider_id: str
    capability_id: str
    input_schema_ref: ProviderOptionsSchemaRef
    output_schema_ref: ProviderOptionsSchemaRef


class ProviderProfile(EntityMeta):
    provider_id: str
    model_id: str
    capability: str
    display_name: str
    environment: Literal["local", "dev", "staging", "prod"]
    secret_ref: str | None = None
    options_schema_ref: ProviderOptionsSchemaRef
    default_options: dict[str, JsonValue] = Field(default_factory=dict)
    enabled: bool = True


class ProviderProfileQuery(BaseListQuery):
    provider_id: str | None = None
    capability: str | None = None
    environment: str | None = None


class CreateProviderProfileRequest(ContractModel):
    provider_id: str
    model_id: str
    capability: str
    display_name: str
    environment: Literal["local", "dev", "staging", "prod"]
    secret_ref: str | None = None
    options_schema_ref: ProviderOptionsSchemaRef
    default_options: dict[str, JsonValue] = Field(default_factory=dict)


class PatchProviderProfileRequest(ContractModel):
    display_name: str | None = None
    enabled: bool | None = None
    secret_ref: str | None = None
    default_options: dict[str, JsonValue] | None = None


class TestProviderProfileRequest(ContractModel):
    sample_input: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderHealthCheckResponse(ContractModel):
    profile_id: str
    ok: bool
    latency_ms: int | None = None
    error: ProviderError | None = None


class ProviderPriceCatalog(EntityMeta):
    provider_id: str
    status: Literal["draft", "approved", "published", "deprecated"] = "draft"
    currency: str = "CNY"


class ProviderPriceItem(EntityMeta):
    catalog_id: str
    provider_id: str
    model_id: str
    capability_id: str
    unit: Literal["input_token", "output_token", "media_second", "call"]
    unit_price: Money
    active_from: datetime = Field(default_factory=utcnow)
    active_to: datetime | None = None


class PriceCatalogQuery(BaseListQuery):
    provider_id: str | None = None
    active_only: bool = False


class UpsertPriceCatalogRequest(ContractModel):
    catalog: ProviderPriceCatalog
    items: list[ProviderPriceItem]


class ProviderUsageQuery(ContractModel):
    window_start: datetime
    window_end: datetime
    provider_id: str | None = None
    case_id: str | None = None


class ProviderUsageReport(ContractModel):
    invocations: int
    estimated_cost: Money
    actual_cost: Money | None = None
    unpriced_invocation_count: int


class GovernedActionRequest(ContractModel):
    reason: str


class ProviderBalanceQuery(ContractModel):
    provider_id: str | None = None
    account_group: str | None = None
    environment: Literal["local", "dev", "staging", "prod"] | None = None


class ProviderBalanceItem(ContractModel):
    provider_id: str
    account_group: str | None = None
    balance: Money | None = None
    quota_remaining: float | None = None
    unit: str | None = None
    checked_at: datetime
    status: Literal["ok", "low", "unknown", "failed"]


class ProviderBalanceReport(ContractModel):
    items: list[ProviderBalanceItem]
    request_id: str


class ReconcileBillingRequest(ContractModel):
    provider_id: str | None = None
    window_start: datetime
    window_end: datetime
    dry_run: bool = False


class ReconcileBillingResponse(ContractModel):
    reconciliation_run_id: str
    status: Literal["queued", "running"]
    request_id: str


class ScriptVersion(EntityMeta):
    case_id: str
    title: str
    script: str
    creative_intent_artifact_id: str | None = None
    adopted_from_draft_id: str | None = None


class VideoVersion(EntityMeta):
    case_id: str
    script_version_id: str | None = None
    finished_video_id: str | None = None
    timeline_plan_artifact_id: str
    style_plan_artifact_id: str


class PublishRecord(EntityMeta):
    case_id: str
    video_version_id: str | None = None
    publish_package_id: str | None = None
    publish_batch_id: str | None = None
    platform: str
    status: Literal["draft", "submitted", "published", "failed"] = "draft"
    cover_artifact_id: str | None = None
    published_at: datetime | None = None


class PerformanceObservation(EntityMeta):
    case_id: str
    publish_record_id: str
    metric_name: str
    metric_value: float
    observed_at: datetime = Field(default_factory=utcnow)


class PerformanceMetricView(ContractModel):
    impressions: int = 0
    clicks: int = 0
    views: int = 0
    likes: int = 0
    conversion_rate: float | None = None


class CreativeFeatureVector(ContractModel):
    hook_type: str | None = None
    duration_sec: float | None = None
    broll_count: int = 0
    title_tokens: int = 0


class CaseMemoryScope(ContractModel):
    channel: str | None = None
    audience: str | None = None
    product: str | None = None


class CaseMemory(EntityMeta):
    case_id: str
    status: Literal["proposed", "approved", "active", "deprecated", "rejected", "superseded"] = "proposed"
    scope: CaseMemoryScope = Field(default_factory=CaseMemoryScope)
    insight: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0, le=1)


class MemoryProposal(CaseMemory):
    proposed_by_reflection_run_id: str | None = None


class ReflectionRun(EntityMeta):
    case_id: str
    status: RunStatus = RunStatus.created
    window: Literal["24h", "3d", "7d", "30d"] = "7d"
    report_artifact_id: str | None = None


class CaseAgentSourceBinding(EntityMeta):
    case_id: str
    source_type: Literal["url", "text", "file", "manual_note"]
    source_ref: str
    title: str | None = None


class CreativeBrief(EntityMeta):
    case_id: str
    summary: str
    source_binding_ids: list[str] = Field(default_factory=list)


class ScriptDraft(EntityMeta):
    case_id: str
    title: str
    script: str
    status: Literal["draft", "adopted", "rejected"] = "draft"
    memory_ids: list[str] = Field(default_factory=list)


class CaseAgentRun(EntityMeta):
    case_id: str
    goal: Literal["brief", "script_draft", "memory_proposal"]
    status: RunStatus = RunStatus.created
    source_binding_ids: list[str] = Field(default_factory=list)


class CaseAgentRunQuery(BaseListQuery):
    status: str | None = None


class CreateSourceBindingRequest(ContractModel):
    source_type: Literal["url", "text", "file", "manual_note"]
    source_ref: str
    title: str | None = None


class ImportCaseSourceRequest(ContractModel):
    source_binding_id: str
    provider_profile_id: str | None = None


class StartCaseAgentRunRequest(ContractModel):
    goal: Literal["brief", "script_draft", "memory_proposal"]
    source_binding_ids: list[str] = Field(default_factory=list)


class CaseAgentRunDetail(ContractModel):
    run: CaseAgentRun
    briefs: list[CreativeBrief] = Field(default_factory=list)
    drafts: list[ScriptDraft] = Field(default_factory=list)
    memory_proposals: list[MemoryProposal] = Field(default_factory=list)


class ScriptDraftQuery(BaseListQuery):
    status: str | None = None


class AdoptScriptDraftRequest(ContractModel):
    title: str | None = None
    publish_content: str | None = None


class MemoryProposalQuery(BaseListQuery):
    status: str | None = None


class ApproveMemoryRequest(ContractModel):
    reason: str | None = None


class RejectMemoryRequest(ContractModel):
    reason: str


class CaseKnowledgeResponse(ContractModel):
    case_id: str
    memories: list[CaseMemory]
    recent_script_versions: list[ScriptVersion]
    recent_video_versions: list[VideoVersion]


class CasePerformanceQuery(ContractModel):
    window: Literal["24h", "3d", "7d", "30d"] = "7d"


class CasePerformanceResponse(ContractModel):
    metrics: PerformanceMetricView
    observations: list[PerformanceObservation]


class StartReflectionRunRequest(ContractModel):
    window: Literal["24h", "3d", "7d", "30d"] = "7d"
    force: bool = False


class GenerateScriptWithMemoryRequest(ContractModel):
    brief: str
    memory_ids: list[str] = Field(default_factory=list)


class PerformanceAttributionResponse(ContractModel):
    video_version_id: str
    feature_vector: CreativeFeatureVector | None = None
    observations: list[PerformanceObservation]
    contributing_memories: list[CaseMemory] = Field(default_factory=list)


class CreativePattern(EntityMeta):
    case_id: str
    label: str
    lift: float | None = None
    evidence_count: int = 0


class CaseInsightCard(EntityMeta):
    case_id: str
    title: str
    body: str
    severity: Literal["info", "warning", "success"] = "info"


class MetricsImportRequest(ContractModel):
    rows: list[dict[str, JsonValue]]
    dry_run: bool = False


class FinishedVideo(EntityMeta):
    case_id: str
    run_id: str | None = None
    title: str
    video_artifact: ArtifactRef
    cover_artifact: ArtifactRef | None = None
    subtitle_artifact: ArtifactRef | None = None
    duration_sec: float = 0
    qc_status: Literal["pending", "passed", "failed", "warning"] = "pending"


class FinishedVideoQuery(BaseListQuery):
    case_id: str | None = None
    qc_status: str | None = None


class FinishedVideoDetail(ContractModel):
    finished_video: FinishedVideo
    video_version: VideoVersion | None = None
    publish_records: list[PublishRecord] = Field(default_factory=list)


class PublishDefaults(ContractModel):
    title: str
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)


class PublishPackage(EntityMeta):
    case_id: str | None = None
    source_finished_video_id: str | None = None
    upload_artifact_id: str | None = None
    video_artifact: ArtifactRef
    cover_artifact: ArtifactRef | None = None
    platform_defaults: PublishDefaults


class CreateEditorHandoffRequest(ContractModel):
    format: Literal["zip", "folder_manifest"] = "zip"


class EditorHandoffPackageArtifact(ContractModel):
    package_artifact: ArtifactRef
    manifest: dict[str, JsonValue]


class CreateJianyingDraftRequest(ContractModel):
    template_id: str | None = None


class JianyingDraftPackageArtifact(ContractModel):
    package_artifact: ArtifactRef
    draft_manifest: dict[str, JsonValue]


class PublishPackageQuery(BaseListQuery):
    case_id: str | None = None
    source_type: str | None = None


class CreatePublishPackageRequest(ContractModel):
    source_finished_video_id: str | None = None
    upload_artifact_id: str | None = None
    title: str
    description: str = ""


class PublishBatchStatus(str, Enum):
    draft = "draft"
    processing = "processing"
    review_ready = "review_ready"
    publishing = "publishing"
    completed = "completed"
    partial_failed = "partial_failed"


class PublishItemStatus(str, Enum):
    uploaded = "uploaded"
    normalizing = "normalizing"
    asr_running = "asr_running"
    copy_running = "copy_running"
    cover_running = "cover_running"
    review_ready = "review_ready"
    manual_review_ready = "manual_review_ready"
    publishing = "publishing"
    published = "published"
    generation_failed = "generation_failed"
    publish_failed = "publish_failed"
    excluded = "excluded"


class PublishAttemptStatus(str, Enum):
    created = "created"
    manual_review_ready = "manual_review_ready"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"


class PublishBatchItemVm(EntityMeta):
    publish_package_id: str
    platform: str
    title: str
    description: str = ""
    selected: bool = True
    status: PublishItemStatus = PublishItemStatus.uploaded


class PublishBatchVm(EntityMeta):
    status: PublishBatchStatus = PublishBatchStatus.draft
    items: list[PublishBatchItemVm] = Field(default_factory=list)


class PublishBatchQuery(BaseListQuery):
    status: str | None = None


class CreatePublishBatchRequest(ContractModel):
    publish_package_ids: list[str]
    platform_targets: list[str]


class SubmitPublishBatchRequest(ContractModel):
    dry_run: bool = False


class PatchPublishItemRequest(ContractModel):
    title: str | None = None
    description: str | None = None
    selected: bool | None = None


class PublishAttempt(EntityMeta):
    item_id: str
    platform: str
    status: PublishAttemptStatus = PublishAttemptStatus.created
    error: ProviderError | None = None


class PublishAttemptDetail(ContractModel):
    attempt: PublishAttempt
    record: PublishRecord | None = None


class OpsDashboardQuery(ContractModel):
    window_start: datetime
    window_end: datetime


class CostRollup(EntityMeta):
    group_key: str
    group_by: str | None = None
    estimated_cost: Money
    actual_cost: Money | None = None
    invocations: int = 0


class CostRollupQuery(OpsDashboardQuery):
    group_by: Literal["case", "provider", "model", "prompt_version", "run", "job"] | None = None


class YieldFunnelEvent(EntityMeta):
    case_id: str | None = None
    run_id: str | None = None
    event_name: str
    affects_true_yield: bool = True


class YieldFunnelQuery(OpsDashboardQuery):
    case_id: str | None = None


class YieldFunnelResponse(ContractModel):
    events: list[YieldFunnelEvent]
    true_yield_rate: float | None = None


class Budget(EntityMeta):
    scope_type: str
    scope_id: str | None = None
    limit: Money
    alert_threshold: float = Field(0.8, ge=0, le=1)
    enabled: bool = True


class BudgetQuery(BaseListQuery):
    scope_type: str | None = None


class UpsertBudgetRequest(ContractModel):
    budget: Budget


class PatchBudgetRequest(ContractModel):
    limit: Money | None = None
    alert_threshold: float | None = None
    enabled: bool | None = None


class OpsAlertEvent(EntityMeta):
    code: str
    status: Literal["open", "acknowledged", "resolved"] = "open"
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class AcknowledgeAlertRequest(ContractModel):
    note: str | None = None


class ResolveAlertRequest(ContractModel):
    resolution: str


class ProductionQualityCheck(EntityMeta):
    target_type: Literal["run", "finished_video"]
    target_id: str
    check_type: Literal["auto", "manual", "platform_feedback"] = "manual"
    result: Literal["passed", "failed", "warning", "manual_required"]
    reason_code: str | None = None
    evidence_artifact_id: str | None = None
    affects_true_yield: bool = True


class CreateQualityCheckRequest(ContractModel):
    check_type: Literal["auto", "manual", "platform_feedback"] = "manual"
    result: Literal["passed", "failed", "warning", "manual_required"]
    reason_code: str | None = None
    evidence_artifact_id: str | None = None
    affects_true_yield: bool = True


class ApprovalRequest(EntityMeta):
    resource_type: str
    resource_id: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    reason: str | None = None


class ApprovalDecisionRequest(ContractModel):
    reason: str


class AuditEvent(EntityMeta):
    actor: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AuditEventQuery(BaseListQuery):
    actor: str | None = None
    resource_type: str | None = None
    action: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


class OpsDashboardVm(ContractModel):
    usage: ProviderUsageReport
    yield_funnel: YieldFunnelResponse
    alerts: list[OpsAlertEvent]
    cost_rollups: list[CostRollup]


class ImportBatchStatus(str, Enum):
    created = "created"
    running = "running"
    completed = "completed"
    failed = "failed"
    partially_failed = "partially_failed"


class CreateImportBatchRequest(ContractModel):
    import_type: Literal[
        "case",
        "script",
        "media",
        "finished_video",
        "video_version",
        "publish_record",
        "performance",
        "prompt_seed",
        "provider_price",
    ]
    rows_artifact_id: str | None = None
    rows: list[JsonValue] | None = None
    dry_run: bool = False
    idempotency_key: str | None = None


class ImportRowResult(ContractModel):
    row_index: int
    status: Literal["created", "skipped", "failed"]
    external_id: str | None = None
    internal_id: str | None = None
    error: NodeError | None = None


class ImportBatchReport(ContractModel):
    batch_id: str
    import_type: str
    status: ImportBatchStatus
    created_count: int
    skipped_count: int
    failed_count: int
    results: list[ImportRowResult]
    mapping_artifact_id: str | None = None
    request_id: str


class OutboxEvent(EntityMeta):
    topic: str
    aggregate_type: str
    aggregate_id: str
    payload_schema: str
    payload: JsonValue
    status: Literal["pending", "published", "failed"] = "pending"
    attempts: int = 0
    available_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    last_error: str | None = None
    dedupe_key: str | None = None


def signed_local_url(path: str, minutes: int = 15) -> SignedUrlResponse:
    return SignedUrlResponse(
        url=f"local://{path}",
        expires_at=utcnow() + timedelta(minutes=minutes),
        request_id="req_local",
    )
