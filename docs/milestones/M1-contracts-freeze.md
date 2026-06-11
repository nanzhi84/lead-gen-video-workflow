# M1 施工简报：契约定版冻结

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m1-contracts-freeze`
Spec：仓库根 `树影_Cutagent_CleanSlate重写Spec_v3_2026-06-11.md`（引用行号均指该文件；第 32 章是终值，与前文冲突以 32 章为准）

## Goal

把 `packages/core/contracts` 修到与 spec 完全一致并冻结；建立共享状态机迁移表；统一 API 错误体。
之后所有 milestone 都在这套契约上施工——本批不修业务语义（假发布、sandbox provider 等留给 M6+），
但**必须把所有调用点机械地跟进改名/改形**，保持全部 54 个测试绿（允许按新契约改测试断言，不允许删测试）。

## 改动清单（逐条核销，验收按此打勾）

### A. 金额与计费契约

- A1 `Money`：`amount: Decimal`、`currency: str`（必填，ISO 4217 三字母）、`amount_micro: int | None`（spec 2527-2538）。所有用 float 算钱的地方改 Decimal/micro。
- A2 `UsageMeterRecord` 补全：`cached_input_tokens`、`image_count`、`provider_credits: Decimal|None`、`raw_usage: dict`；`media_seconds` 拆回 `audio_seconds` + `video_seconds`（spec 2543-2557）。
- A3 `ProviderInvocation` 补：`usage: UsageMeterRecord|None`、`price_item_id`、`billing_status: Literal["estimated","reconciled","unpriced","ignored"]`、`external_job_id`、`started_at/finished_at`（spec 780-802）。

### B. 状态机

- B1 `ProviderStatus` 换回 spec 七态：`prepared/submitted/polling/succeeded/failed/timed_out/cancelled`（spec 513-524）。`quota_exceeded`、`cost_unpriced` 不是状态，从枚举移除（前者是 ErrorCode，后者是 WarningCode）。
- B2 新建 `packages/core/contracts/state_machines.py`：为 JobStatus、RunStatus（含 cancelling，spec 3283-3291）、NodeStatus、ProviderStatus、PromptVersion.status、CaseMemory.status、UploadSessionStatus、PublishBatchStatus、PublishItemStatus、PublishAttempt.status 定义合法迁移表（dict[Enum, frozenset[Enum]]）+ `assert_transition(kind, from, to)`，非法迁移抛 `workflow.invalid_transition` 的类型化异常（spec 449-455, 469-482, 497-505, 3264-3276）。
- B3 把现有所有"直接 setattr 状态"的写点接上 assert_transition：prompts approve/publish/rollback（draft 不得跳级）、upload complete/cancel（cancelled/expired 不得 complete，completed 不得 cancel）、case memory approve（proposed→approved→active，不得一步到 active）、publishing batch/item/attempt、provider invocation、job/run/node。
- B4 `CaseMemory.status` 枚举补全六态：`proposed/approved/active/deprecated/rejected/superseded`（spec 3878-3882）。

### C. Schema 版本化与判别 union

- C1 `DigitalHumanVideoRequest` 加 `schema_version: Literal["digital_human_video_request.v1"]`（spec 572）；其余三种 Request 同样加各自 literal。
- C2 `Job` 加 `request_schema: str` 和 `latest_finished_video_id: str|None`；`request` union 用 pydantic discriminator（按 schema_version 或 type 字面量判别），不靠从左到右尝试（spec 552-566）。
- C3 字段名对齐 spec：`created_by_user_id`→`created_by`、`current_run_id`→`active_run_id`、`retry_from_run_id`→`retry_of_run_id`。
- C4 `EntityMeta`：补 `created_by: str|None`、`version: int = 1`（spec 535-541）。
- C5 `WorkflowRun` 补 `requested_by`、`experiment_assignment_id`（spec 652-668）。
- C6 `NodeRun` 补 `attempt: int = 1`、`skipped_reason: str|None`、`degradation_reason: str|None`；`input_manifest_hash` 改回必填（spec 673-690）。

### D. Artifact 契约

- D1 `ArtifactKind` 按 spec 32.1 终值全集修正（spec 3673-3711）：`spec.validated_production`、`editor.handoff_package`、`editor.jianying_draft_package`、补 `case.performance_analysis`、`script.strategy`、`lipsync.report`、`provider.raw_request`、`provider.raw_response`、`audio.alignment.raw`、`narration.units` 等。现有持久化值若不一致一律改为 spec 值（无存量数据，正是改的最后窗口）。
- D2 `ArtifactRef` 补必填 `uri`（spec 729-734）；`Artifact` 补 `local_path/oss_uri/size_bytes/immutable: bool = True/retention_policy: str = "default"`（spec 736-753）。
- D3 `MediaInfo`：补必填 `media_type: Literal["video","audio","image","subtitle","json"]`、`codec`、`format`；`frame_rate` 改名 `fps`（spec 765-775）。
- D4 新建 `packages/core/contracts/artifacts.py`：按 spec 24.2 + 32.2（行 2694-2833、3719-3808）实现全部 artifact payload 模型与 `ArtifactSchemaRegistry`（kind+schema_version → pydantic model），写入前校验、读取按模型反序列化。payload_schema 命名与 spec 32.2 映射表一致（如 `MaterialPackArtifact` 不是 `MaterialPackPlanArtifact.v1`）。
- D5 32.6 强类型替换（spec 3982-4042）：`MaterialCandidate`、`SubtitleStylePlan`、`BgmPlan`、`FontPlan`、`TimelineValidationReport`、`CostSummary`、`NodeSummary`，并替换 `MaterialPackArtifact.*_candidates`、`StylePlanArtifact.subtitle/bgm/font`、`TimelinePlanArtifact.validation`、`RunPublicReportArtifact.cost_summary/node_summaries` 的 dict。
- D6 32.5/23.9 类型：`AnnotationTimelineRow`、`QualityEventRow`、`FieldUiMetadata`、`AnnotationEditView`、`AnnotationPatchRequest`（含 `annotation_id`、`base_etag`、`reason`）。
- D7 pipeline 节点（`packages/production/pipeline/digital_human.py`）手拼 dict 的 payload 全部换成 D4 模型实例 dump；下游 `.payload.get(...)` 改为模型解析。NarrationAlignment 的均分估算必须标 `source="estimated"` 并在 strict 模式下按 spec 拒绝（spec 1077-1083 策略顺位不许伪装成 tts_subtitle）。TimelinePlanning 删掉硬编码假 validation report——本批先实现真实的重叠/负时长/越界三项检查 + 30fps 帧量化（`total_frames`、`timeline_*_frame` 整数帧，spec 1157-1166、2785-2798）。

### E. Provider / Capability / Secrets / Options 契约

- E1 Capability id 统一为 spec 点分命名：`llm.chat`、`vlm.annotation`、`tts.speech`、`asr.transcribe`、`lipsync.video`、`image.generate`、`image.edit`（spec 1795-1802）。代码内短名（tts/llm/lipsync/annotation/cover）全部替换；自创 capability（cover、publish 等）映射到最接近的 spec capability 或移除。
- E2 `ProviderProfile` 补：`concurrency_key`、`timeout_sec`、`retry_policy`、`cost_policy_id`、`version`；`ProviderOptionsSchemaRef` 补 `dialect`、`sha256`（spec 1810-1832）。
- E3 `ProviderCapability` 按 spec 23.8 补全字段（spec 2648-2661）。
- E4 `RetryPolicy` 补 `retryable_error_codes` + 字段约束；`ResumePolicy` 改为 spec 形：`mode`/`reusable_artifact_kinds`/`side_effect_replay`（spec 2580-2589）。
- E5 Secrets 契约对齐 spec 11.3（spec 1843-1882）：`SecretRecord`（`secret_ref`/`status: active|disabled|rotated`/`rotated_from_secret_id`/`disabled_at` 等）、`SecretPreview`、`RotateSecretRequest(reason)`。rotate 必须创建新记录、旧记录置 rotated 并链 `rotated_from_secret_id`——不是原地改回 active。本批只修契约与状态机；密文存储后端（secret_ref 指向外部 store）留给 M2，但 DB 不得再存 sha256(明文) 充当"加密值"，临时方案为 dev-only 可逆封装并打 TODO(M2)。
- E6 `WarningCode` 按 spec 27.1 收敛为单一枚举（值含 `broll.skipped_no_material`、`timestamp.estimated`、`cost.unpriced` 等，spec 3246-3252）；`DegradationNotice` 按 spec 形（code/message/node_id/affects_true_yield/details）。NodeRun 的降级信息用 `degradation_reason` + DegradationNotice，不再用裸 code 列表。
- E7 请求 options 对齐 spec 5.3（spec 591-647）：`VoiceOptions`（voice_id 必填、补 emotion/volume）、`PortraitOptions`（template_mode/specific_template_id/template_sequence_ids/rhythm_preset）、`BrollOptions`（enabled 默认 True、max_inserts/min_segment_duration）、`SubtitleOptions`（字段名 subtitle，style_preset/font_id/font_size/position）、`BgmOptions`、`CoverOptions`、`OutputOptions`、`StrictnessOptions`。`LipSyncOptions.options: dict` 这类逃生舱删除。

### F. 统一错误体与 request_id

- F1 加 `RequestValidationError` exception handler：422 也返回 spec 4.1 统一错误体（spec 362-378）。
- F2 替换 `apps/api/main.py` 五处裸 `HTTPException`（行 1846/1859/1894/1904/1912 一带，publishing 端点）为统一错误体。
- F3 request_id 中间件：每请求生成一次，贯穿 error body 与响应（响应头 `X-Request-Id`），不再每次调用 `request_id()` 拿到不同值。
- F4 Auth 契约对齐 spec 33.1（spec 4299-4342）：`AuthUser.status: Literal["active","disabled"]`（替代 disabled:bool）、`SessionInfo.session_id`、`ChangePasswordRequest.old_password`、`AdminCreateUserRequest` 按 spec 形。
- F5 `UploadKind` 改回 spec 七业务值（portrait/broll/voice_reference/bgm/font/cover_template/publish_video，spec 4385-4392）；`CompleteUploadResponse` 补 `media_asset`/`publish_package` 字段（complete 创建 MediaAssetRecord 的行为本批一并实现，spec 4453-4469 绑定矩阵）。
- F6 Publishing 状态枚举对齐附录 F（spec 3299-3360）：`PublishBatchStatus`、`PublishItemStatus`、`PublishAttempt` 全字段。仅契约与状态机，假发布语义 M6 修。

## 边界（Out of scope，禁止顺手做）

- 不动存储后端选择（内存默认问题是 M2）；不引 temporalio（M3）；不加 WebSocket/日志/metrics(M4)；
  不拆 main.py（M2）；不实现真实 provider/媒体处理。
- SQLAlchemy 表结构需要跟着契约字段改的，一并改（无存量数据，直接改 `database.py` 与 alembic 初版迁移，不写增量迁移链）。

## Verification（Codex 自验，验收官复验）

```bash
cd <worktree>
/home/nanzhi/projects/cutagent-genesis/.venv/bin/python -m pytest -q                    # 全绿
CUTAGENT_RUN_DB_TESTS=1 CUTAGENT_STORAGE_BACKEND=sqlalchemy \
CUTAGENT_DATABASE_URL='postgresql+psycopg://cutagent:cutagent@127.0.0.1:55432/cutagent' \
/home/nanzhi/projects/cutagent-genesis/.venv/bin/python -m pytest tests/integration -q  # 全绿
/home/nanzhi/projects/cutagent-genesis/.venv/bin/python scripts/export_openapi.py       # 可导出
```

新增测试要求：

- `tests/contract/test_state_machines.py`：每个状态机的合法/非法迁移（含 failed→running 禁止、draft prompt 跳级禁止、cancelled upload 不可 complete）。
- `tests/contract/test_artifact_schema_registry.py`：每个 JSON ArtifactKind 都能在 registry 找到模型；URI-only kind 校验 MediaInfo+sha256 规则。
- `tests/contract/test_error_envelope.py`：422、404、409 都返回统一错误体且带 request_id；同一请求内 request_id 一致。
- 钱字段断言 Decimal/micro 不丢精度。
