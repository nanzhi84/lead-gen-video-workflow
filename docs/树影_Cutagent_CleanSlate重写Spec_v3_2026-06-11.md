# 树影 / Cutagent Clean-Slate 可实施重写 Spec v3

生成日期：2026-06-11  
用途：交给另一个 Agent，在不依赖原仓库代码上下文的情况下，从零重写整套系统  
定位：施工图，不是愿景稿  
第一版参考文件：`C:\Users\Nanzhi\Desktop\树影_Cutagent_origin-dev_架构重写Spec_2026-06-11.md`  
本版状态：Clean-slate 版。保留产品能力和业务目标，不要求兼容旧仓库代码、旧数据库、旧 API 或旧文件结构；历史素材和数据可按新系统标准从 0 重新导入。技术选型以长期工程质量、性能、可观测性和可扩展性优先。  

---

## 0. 给实施 Agent 的第一句话

你要重写的不是一个“脚本转视频工具”，而是一套围绕 **Case** 长期进化的数字人内容生产系统。

系统的核心不是单条视频，而是一个 case 的持续学习闭环：

```text
Case
  -> 历史脚本 / 历史成片 / 素材 / 发布记录 / 平台表现
  -> Agent 总结哪些脚本、剪辑、素材、封面、标题表现更好
  -> 形成可审核的 Case Memory
  -> 下一轮生成脚本与剪辑计划时显式使用这些经验
  -> 生产并发布新视频
  -> 回收表现数据
  -> 再反思、再进化
```

视频生产流水线只是这个系统的一条主执行链。它必须服务于 case 的长期进化，而不是只追求“这一条视频跑完”。

---

## 1. 本版硬约束

### 1.1 从零重写，不背旧仓库包袱

本 spec 的目标是 **clean-room rewrite + fresh import + clean cutover**。

意思是：

- 不复用旧代码，不要求旧 API 兼容，不要求旧数据库结构兼容。
- 不需要把旧 `queue.sqlite3`、旧 JSON、旧 publish batch、旧 annotation 槽位完整迁入。
- 旧素材和历史数据如果还需要使用，应按新系统的上传/导入协议重新导入，生成新的 `MediaAsset`、`Artifact`、`Case`、`ScriptVersion`、`FinishedVideo` 等实体。
- 必须保留的是“产品能力”和“业务闭环”，不是旧实现方式。
- 可以重新设计目录、表、服务、前端、运行时和部署拓扑。
- 所有旧系统概念只作为理解参考，不作为兼容目标。

不得为了兼容旧逻辑牺牲新架构的清晰性、性能和可维护性。

### 1.2 所有边界必须强契约

任何跨以下边界的数据，都必须是版本化 schema：

- API request / response
- WebSocket event
- workflow node input / output
- provider request / response
- repository read / write
- frontend ViewModel
- artifact payload
- prompt variables / output

禁止把未版本化 `dict` / `Any` 作为业务契约。只有 debug trace 可以用松散 JSON，且 debug trace 不能被下游业务逻辑消费。

### 1.3 Case 是长期学习边界

Case 不是文件夹，不只是工作台入口。Case 是长期学习单元，必须有：

- 脚本版本历史
- 视频版本历史
- 发布历史
- 表现指标
- 素材使用历史
- 剪辑计划历史
- prompt / 模型 / provider 使用历史
- 反思报告
- 长期记忆
- 下一轮创作策略

### 1.4 Workflow 节点只做一件事

每个 workflow node 必须：

- 有明确输入 schema。
- 有明确输出 artifact。
- 有明确错误码。
- 有幂等规则。
- 有重试/续跑规则。
- 不直接读写其他节点私有状态。
- 不直接拼生产 prompt。
- 不直接写前端展示字段。

### 1.5 Provider 是插件

想换 lipsync / TTS / ASR / VLM / image 模型时，应该主要新增 provider plugin 和配置，不应修改 production pipeline。

### 1.6 运营中台是一等模块

API 价格、调用成本、成品率、失败率、prompt 版本、provider 余额、审计、告警，都必须纳入统一运营中台。不能只在日志里查。

### 1.7 自动兜底必须分级

不是所有 fallback 都禁止。必须区分：

- `hard_fail`：必须失败，例如人像主轨素材不足、timeline 非法、provider 不支持请求参数。
- `soft_degrade`：可产出但必须在报告里写清楚，例如 B-roll 不足、BGM 曲库无标注。
- `warning_only`：不影响出片但提示，例如封面 fallback 到视频帧。

任何降级都必须出现在 run report 和 yield/quality 统计里。

---

## 1A. Clean-Slate 技术选型

本版不默认沿用旧仓库技术。以下为推荐默认选型，除非有明确反证，不应降级。

### 1A.1 后端与 API

- Python 3.12+。
- FastAPI + Pydantic v2，作为 HTTP API 和 OpenAPI schema 源。
- SQLAlchemy 2 + Alembic，管理数据库模型与迁移。
- Granian 或 Uvicorn 作为 ASGI server；生产用多进程部署。
- Argon2id 做密码 hash，HttpOnly cookie session 做 Web 登录。

### 1A.2 工作流运行时

- 生产默认使用 Temporal。
- Temporal workflow 负责 durable orchestration、retry、signal、query、cancel、activity timeout。
- 每个本 spec 中的 Node 对应 Temporal Activity；Workflow 只编排，不做重 CPU/IO 工作。
- 本地开发提供 docker-compose 启动 Temporal。
- 领域代码只依赖 `WorkflowRuntimeAdapter`，不得让领域节点 import 具体 runtime SDK。

选择 Temporal 的原因：长视频生产有长耗时外部 job、取消、续跑、幂等、超时、信号和可恢复需求，Temporal 的 durable execution 语义更贴近目标系统。

### 1A.3 数据库、搜索与时间序列

- PostgreSQL 16+ 作为唯一主数据库。
- pgvector 存 case knowledge / script / memory embedding。
- TimescaleDB extension 可选，用于 provider usage、yield funnel、performance observations 等时间序列聚合；不用 Timescale 时也必须用普通 Postgres 表实现同等语义。
- Redis 7 用于短期 cache、rate limit、WebSocket fanout，不作为真相源。

### 1A.4 对象存储

- 所有文件通过 S3-compatible ObjectStore 抽象。
- 本地开发使用 MinIO。
- 生产可用阿里云 OSS / S3，但业务代码只看 ObjectStore。
- 本地磁盘只做 worker cache 和临时文件。

### 1A.5 事件与可观测性

- OpenTelemetry 统一 trace/metrics/log correlation。
- Prometheus + Grafana 做运行指标。
- Sentry 或同类工具做异常聚合。
- Postgres outbox + Redis/NATS fanout 做 WebSocket 事件；若使用 NATS JetStream，事件仍须落库为可恢复 outbox。

最低 Observability Contract：

- 所有结构化日志必须包含可用的 `request_id`、`trace_id`、`user_id`、`case_id`、`job_id`、`run_id`、`node_run_id`、`provider_invocation_id`、`prompt_invocation_id`；无上下文时填 `null`，不得省略字段。
- API span 命名：`api.{method}.{route_name}`；Temporal workflow span 命名：`workflow.{workflow_template_id}.{version}`；activity span 命名：`activity.{node_id}.{node_version}`；provider span 命名：`provider.{provider_id}.{capability_id}.{model_id}`。
- Provider 调用必须记录 `duration_ms`、`status`、`error_code`、`retry_count`、`input_tokens`、`output_tokens`、`media_seconds`、`estimated_cost`、`actual_cost`、`provider_id`、`model_id`、`capability_id`。
- Prometheus 至少暴露：`api_request_duration_seconds`、`api_request_errors_total`、`workflow_run_duration_seconds`、`node_run_duration_seconds`、`node_run_retries_total`、`provider_invocation_duration_seconds`、`provider_invocation_failures_total`、`provider_cost_estimated_total`、`provider_unpriced_invocations_total`、`yield_funnel_events_total`、`outbox_lag_seconds`、`temporal_activity_failures_total`。
- Sentry event 必须带 `case_id/job_id/run_id/node_run_id/provider_invocation_id/prompt_invocation_id/prompt_version_id` tags，并附上 `error_code`、`node_id`、`provider_id`。
- `outbox_events` 最低字段：`id`、`topic`、`aggregate_type`、`aggregate_id`、`payload_schema`、`payload`、`status`、`attempts`、`available_at`、`created_at`、`published_at`、`last_error`。
- outbox replay 必须按 `created_at,id` 稳定排序；同一 `aggregate_type + aggregate_id + topic + dedupe_key` 必须幂等；WebSocket/NATS 只消费 outbox，不直接消费业务表事务中间态。

### 1A.6 前端

- React 18+ / Vite / TypeScript。
- TanStack Query 管理 server state。
- TanStack Router 或 React Router 均可，但路由必须类型化。
- OpenAPI 生成 API client 基础类型，不手写一坨大 API 文件。
- Tailwind 可用，但后台/中台页面要以信息密度、表格、筛选、钻取为优先。

### 1A.7 AI 与媒体处理

- Provider 统一走 capability plugin。
- FFmpeg 作为视频/音频处理基础工具。
- PySceneDetect / Silero VAD / OpenCV / librosa 用于确定性媒体传感器。
- 所有 provider 调用都必须落 ProviderInvocation、UsageMeterRecord、PromptInvocation。

### 1A.8 为什么不是 SQLite / JSON / 手写队列

- SQLite/JSON 只适合早期本地工具，不适合 case 长期记忆、运营中台、成本归因、成品率漏斗和多 worker 并发。
- 手写队列不适合长耗时可恢复视频工作流。
- 新系统不再为了兼容旧仓库的本地 JSON/SQLite 形态降低架构质量。

## 2. 产品能力保留矩阵（非旧逻辑兼容）

另一个 Agent 即使拿不到旧仓库，也必须按这个矩阵实现。

### 2.1 必须保留的用户流程

| 流程 | 是否保留 | 新系统归属 |
|---|---:|---|
| 登录、注册、会话、管理员 | 必须 | `apps/api` + `packages/core/auth` |
| Case 列表 / 新建 / 编辑 / 删除 | 必须 | `packages/creative/cases` |
| 进入单个 Case 工作台 | 必须 | `apps/web` Studio |
| 在 Case 内创作视频 | 必须 | `packages/production` |
| Case Agent 读取数据源、生成草稿 | 必须 | `packages/creative/case_agent` |
| 从智能体草稿采用脚本 | 必须 | Case Agent -> ScriptDraft -> Production Job |
| 单条脚本创建视频任务 | 必须 | DigitalHumanVideo Job |
| 批量脚本创建视频任务 | 必须 | Batch Job / multiple Jobs |
| 查看任务队列和成片 | 必须 | Runs / FinishedVideos 页面 |
| 失败任务重跑 | 必须 | 新 run，从头 |
| 失败任务续跑 | 必须 | 新 run，复用合法 artifacts |
| 取消任务 / 强制取消 | 必须 | Workflow cancellation |
| 上传人像素材 / B-roll 素材 | 必须 | Media Asset Library |
| 素材 AI 标注 / 批量标注 | 必须 | Annotation Service |
| 标注编辑器 | 必须 | Annotation Projection + Patch |
| 上传 / 克隆 / 试听音色 | 必须 | Voice Library |
| 上传 / 标注 / 选择 BGM | 必须 | BGM Library + Selection |
| 上传 / 标注 / 选择字体 | 必须 | Font Library + Selection |
| 字幕、BGM、B-roll 配置 | 必须 | Production Options |
| HeyGem lipsync 默认路径 | 必须 | LipSyncProvider |
| VideoReTalk 可作为备选 provider | 可保留 | LipSyncProvider |
| 成片预览、下载、删除 | 必须 | FinishedVideo |
| 剪映草稿 / 编辑器交接 | 必须 | EditorHandoff package |
| 发布中心 | 必须 | `packages/publishing` |
| 从成片创建发布批次 | 必须 | FinishedVideo -> PublishPackage |
| 上传视频创建发布批次 | 必须 | User upload -> PublishPackage |
| AI 封面 / 截帧封面 | 必须 | Cover Service |
| 发布文案生成 | 必须 | Publishing Copy Node |
| 小V猫发布适配 | 必须 | PublishPlatformAdapter |
| 巨量/OceanEngine 离线导入 | 保留为 connector | `apps/connectors/oceanengine` |
| 设置页 API keys / provider balances | 必须 | Admin / Ops |
| WebSocket 进度 | 必须 | Run Events |

### 2.2 可以降级但必须显式报告的能力

| 能力 | 降级方式 | 报告要求 |
|---|---|---|
| B-roll 素材不足 | 不插 B-roll | run report 写 `broll.skipped_no_material` |
| BGM 曲库无可用标注 | 不配 BGM | run report 写 `bgm.skipped_library_unannotated` |
| 字体选择失败 | 使用 case 默认字体 | run report 写 `font.default_used` |
| 封面生成失败 | 使用视频帧封面 | run report 写 `cover.frame_fallback` |
| 平台指标暂未回流 | Case reflection 暂不更新 memory | insight 页面显示数据等待中 |

### 2.3 不允许静默降级的能力

| 场景 | 行为 |
|---|---|
| 人像主轨无法覆盖完整音频 | `hard_fail: material.insufficient.portrait` |
| lipsync provider 不支持参数 | `hard_fail: provider.unsupported_option` |
| timeline 片段重叠 / 负时长 / 越界 | `hard_fail: render.invalid_timeline` |
| artifact 文件丢失且无法重算 | `hard_fail: artifact.missing` |
| prompt 输出不符合 schema 且重试耗尽 | `hard_fail: prompt.output_invalid` |
| 标注 schema 失败且重试耗尽 | asset 标记 `annotation_failed`，不进可用池 |
| provider price 缺失 | 调用允许按策略执行，但必须标 `cost_unpriced` 并告警；生产强管控模式下可失败 |

### 2.4 可删除或延后实现的旧能力

| 能力 | 决策 |
|---|---|
| 同步 `/pipeline/full` 生产 API | 删除，统一走 Job/Run |
| 新代码继续使用 `annotation_v3` 命名 | 删除；素材按新 canonical schema 重新标注 |
| 随机选素材/BGM | 删除；改为 deterministic selection + report |
| 旧 Queue 页面概念 | 替换为 Runs / FinishedVideos |
| OceanEngine RPA 和主 API 同进程 | 删除；独立 connector |
| 生产节点手写 prompt | 删除；统一 Prompt Registry |

---

## 3. 新系统整体结构

### 3.1 顶层目录

```text
apps/
  api/                         # FastAPI API gateway, auth, WebSocket
  worker/                      # Temporal worker entrypoint
  web/                         # React frontend
  connectors/
    oceanengine/               # 巨量/OceanEngine RPA and offline import

packages/
  core/
    contracts/                 # shared schemas, enums, errors
    workflow/                  # workflow engine, node runner, artifact runtime
    storage/                   # repositories, DB sessions, object store
    auth/                      # user/session/permission
    observability/             # logs, metrics, tracing, audit

  ai/
    gateway/                   # provider capability registry
    providers/                 # concrete provider plugins
    prompts/                   # prompt registry and render service

  creative/
    cases/                     # case CRUD and case profile
    scripts/                   # script generation, semantic intent
    case_agent/                # data source -> brief -> draft -> memory proposal
    evolution/                 # performance reflection and case self-evolution

  media/
    assets/                    # media asset registry, uploads, thumbnails
    annotation/                # annotation canonical / projection / index
    audio/                     # TTS, ASR, alignment, audio utils
    video/                     # concat, normalize, frame grid, media prep
    rendering/                 # timeline render, subtitles, BGM mix, handoff

  planning/
    selection/                 # case selection ledger and recency
    material/                  # material pack planning
    editing/                   # portrait/broll/style/timeline planning

  production/
    jobs/                      # Job and Run use cases
    pipeline/                  # workflow templates and node specs
    reports/                   # run public/debug report
    publishable/               # FinishedVideo and PublishPackage

  publishing/
    batches/                   # publish batch workflow
    platforms/                 # platform adapters, XiaoVmao
    covers/                    # AI cover and frame cover

  ops/
    cost/                      # price catalog, usage metering, cost attribution
    yield_/                    # yield funnel and quality gate
    alerts/                    # alerting
    audit/                     # audit service
    dashboard/                 # ops dashboard queries
```

### 3.2 依赖规则

禁止跨层乱 import。必须遵守：

| 包 | 可以依赖 | 禁止依赖 |
|---|---|---|
| `core` | 标准库、基础第三方 | 任何业务包 |
| `ai/providers` | `core.contracts`, `core.storage`, `ai.gateway` | `production`, `publishing`, `web` |
| `ai/prompts` | `core`, `ops.audit` | `production.pipeline` 的具体节点实现 |
| `creative` | `core`, `ai`, `media.assets`, `ops` | `media.rendering`, `publishing` |
| `media.annotation` | `core`, `ai`, `media.assets` | `production.pipeline`, `publishing` |
| `planning` | `core`, `media.assets`, `media.annotation`, `creative.cases` | provider HTTP、rendering side effects |
| `media.rendering` | `core`, `media.assets`, `media.video`, `media.audio` | `creative.case_agent`, `publishing` |
| `production.pipeline` | `core.workflow`, `planning`, `media`, `ai.gateway` | provider-specific HTTP logic |
| `publishing` | `FinishedVideo`, `PublishPackage`, user upload | production debug metadata |
| `ops` | `core`, read-only production repositories | 业务节点内部函数 |
| `apps/api` | use case services | 直接 provider HTTP、直接 ffmpeg |

### 3.3 Workflow Runtime 边界

Temporal 是 v3 的默认生产 runtime。领域层只依赖 `WorkflowRuntimeAdapter`，不得直接依赖具体 runtime SDK。

规则：

- 领域 node 不 import Temporal SDK。
- NodeRunner 负责调用 node。
- Temporal adapter 负责把 WorkflowTemplate 映射为 Temporal workflow/activity。
- 如果未来替换 runtime，必须实现同一套 `WorkflowRuntimeAdapter`，不得改变 node 契约。
- API 进程不安装/不直接调用 Temporal SDK。
- `apps/api` 的 use case service 通过 `WorkflowRuntimeAdapter` 发起 start/signal/query/cancel/resume。
- admission、release、resume、reconciliation 必须实现为 Temporal workflow/signal/schedule 或 worker activity，不另写手工调度进程。

---

## 4. 核心状态机和错误契约

### 4.1 通用错误体

所有 API 错误必须返回：

```json
{
  "error": {
    "code": "provider.timeout",
    "message": "口型同步超时，可续跑重试。",
    "retryable": true,
    "severity": "error",
    "details": {},
    "request_id": "req_...",
    "job_id": "job_...",
    "run_id": "run_...",
    "node_run_id": "nr_..."
  }
}
```

### 4.2 ErrorCode

```python
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
    subtitle_failed = "render.subtitle_failed"
    bgm_failed = "render.bgm_failed"
    lipsync_quality_failed = "lipsync.quality_failed"

    qc_failed = "qc.failed"
    publish_failed = "publish.failed"
    manual_rejected = "manual.rejected"
```

### 4.3 JobStatus

```python
class JobStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    archived = "archived"
```

合法迁移：

```text
draft -> queued -> running -> succeeded
draft|queued|running -> cancelled
running -> failed
succeeded|failed|cancelled -> archived
```

### 4.4 RunStatus

```python
class RunStatus(str, Enum):
    created = "created"
    admitted = "admitted"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
```

合法迁移：

```text
created -> admitted -> running -> succeeded
created|admitted|running -> cancelled
running -> failed
```

禁止：

- `failed -> running`
- `failed -> resumed`

Resume 必须创建新 run，并设置 `resume_from_run_id`。

### 4.5 NodeStatus

```python
class NodeStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    skipped = "skipped"
    degraded = "degraded"
    failed = "failed"
    cancelled = "cancelled"
```

合法迁移：

```text
pending -> running -> succeeded
pending -> skipped
running -> degraded
running -> failed
running -> cancelled
```

规则：

- skipped node 也必须写 node_run。
- 如果下游需要 artifact，skipped node 必须写 empty/pass-through artifact。
- degraded node 可以继续，但必须写 degradation reason。

### 4.6 ProviderStatus

```python
class ProviderStatus(str, Enum):
    prepared = "prepared"
    submitted = "submitted"
    polling = "polling"
    succeeded = "succeeded"
    failed = "failed"
    timed_out = "timed_out"
    cancelled = "cancelled"
```

---

## 5. 核心 Schema

以下是必须实现的最低 schema。实现时可以增加字段，但不能删除这里的字段。

### 5.1 标准基础字段

```python
class EntityMeta(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    version: int = 1
```

### 5.2 Job

```python
class JobType(str, Enum):
    digital_human_video = "digital_human_video"
    case_agent_run = "case_agent_run"
    publish_batch = "publish_batch"
    annotation_batch = "annotation_batch"

class Job(BaseModel):
    id: str
    type: JobType
    case_id: str | None
    created_by: str
    status: JobStatus
    request_schema: str
    request: DigitalHumanVideoRequest | CaseAgentRunRequest | PublishBatchRequest | AnnotationBatchRequest
    active_run_id: str | None
    latest_finished_video_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

`request` 必须是按 `type` 判别的强类型 union，禁止裸 dict。

### 5.3 DigitalHumanVideoRequest

```python
class DigitalHumanVideoRequest(BaseModel):
    schema_version: Literal["digital_human_video_request.v1"] = "digital_human_video_request.v1"
    case_id: str
    script: str
    title: str = ""
    publish_content: str = ""
    creative_intent_ref: ArtifactRef | None = None
    workflow_template_id: str = "digital_human_v2"

    voice: VoiceOptions
    portrait: PortraitOptions
    broll: BrollOptions
    lipsync: LipSyncOptions
    subtitle: SubtitleOptions
    bgm: BgmOptions
    cover: CoverOptions
    output: OutputOptions
    strictness: StrictnessOptions
```

```python
class VoiceOptions(BaseModel):
    voice_id: str
    speed: float = Field(1.0, ge=0.5, le=2.0)
    emotion: str = "neutral"
    volume: float = Field(1.0, ge=0.0, le=2.0)
    provider_profile_id: str | None = None

class PortraitOptions(BaseModel):
    template_mode: Literal["agent", "specific", "sequence"]
    specific_template_id: str | None = None
    template_sequence_ids: list[str] = []
    rhythm_preset: Literal["steady", "balanced", "fast"] = "balanced"

class BrollOptions(BaseModel):
    enabled: bool = True
    case_id: str | None = None
    max_inserts: int = Field(4, ge=0, le=20)
    min_segment_duration: float = Field(3.0, ge=0.5)

class LipSyncOptions(BaseModel):
    enabled: bool = True
    provider_profile_id: str = "runninghub.heygem.default"
    ref_image_artifact_id: str | None = None
    video_extension: bool = False
    query_face_threshold: float | None = Field(None, ge=0.0, le=1.0)
    timeout_minutes: int = Field(30, ge=5, le=120)

class SubtitleOptions(BaseModel):
    enabled: bool = True
    style_preset: str = "douyin"
    font_id: str | None = None
    font_size: int | None = None
    position: dict[str, float] | None = None

class BgmOptions(BaseModel):
    enabled: bool = True
    bgm_id: str | None = None
    volume: float = Field(0.25, ge=0.0, le=1.0)
    auto_mix: bool = True

class CoverOptions(BaseModel):
    mode: Literal["none", "frame", "ai"] = "frame"
    template_id: str | None = None

class OutputOptions(BaseModel):
    export_jianying_draft: bool = True
    export_editor_handoff: bool = True
    upload_to_oss: bool = True
    keep_local_originals: bool = False

class StrictnessOptions(BaseModel):
    strict_timestamps: bool = True
    portrait_insufficient_policy: Literal["hard_fail"] = "hard_fail"
    broll_insufficient_policy: Literal["soft_degrade"] = "soft_degrade"
    bgm_unavailable_policy: Literal["soft_degrade"] = "soft_degrade"
```

### 5.4 WorkflowRun

```python
class WorkflowRun(BaseModel):
    id: str
    job_id: str
    workflow_template_id: str
    workflow_version: str
    status: RunStatus
    requested_by: str
    resume_from_run_id: str | None = None
    retry_of_run_id: str | None = None
    experiment_assignment_id: str | None = None
    public_report_artifact_id: str | None = None
    debug_report_artifact_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

### 5.5 NodeRun

```python
class NodeRun(BaseModel):
    id: str
    run_id: str
    node_id: str
    node_version: str
    status: NodeStatus
    attempt: int = 1
    input_manifest_hash: str
    output_artifact_ids: list[str] = []
    provider_invocation_ids: list[str] = []
    error: NodeError | None = None
    skipped_reason: str | None = None
    degradation_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

### 5.6 NodeError

```python
class NodeError(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    severity: Literal["info", "warning", "error", "fatal"] = "error"
    details: dict[str, Any] = {}
```

### 5.7 ArtifactRef / Artifact

```python
class ArtifactKind(str, Enum):
    creative_intent = "creative.intent"
    audio_tts = "audio.tts"
    audio_alignment = "audio.alignment"
    material_pack = "plan.material_pack"
    portrait_plan = "plan.portrait"
    broll_plan = "plan.broll"
    style_plan = "plan.style"
    timeline_plan = "plan.timeline"
    render_plan = "plan.render"
    video_portrait_track = "video.portrait_track"
    video_lipsync = "video.lipsync"
    video_rendered = "video.rendered"
    video_final = "video.final"
    video_finished = "video.finished"
    subtitle_ass = "subtitle.ass"
    cover_image = "cover.image"
    publish_package = "publish.package"
    run_public_report = "run.report.public"
    run_debug_report = "run.report.debug"
    case_context = "case.context"
    case_reflection = "case.reflection"

class ArtifactRef(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    schema_version: str
    uri: str
    sha256: str | None = None

class Artifact(BaseModel):
    id: str
    run_id: str | None
    case_id: str | None
    kind: ArtifactKind
    schema_version: str
    uri: str
    local_path: str | None = None
    oss_uri: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    media: MediaInfo | None = None
    payload: dict[str, Any] | None = None
    created_by_node_run_id: str | None
    immutable: bool = True
    retention_policy: str = "default"
    created_at: datetime
```

Artifact 规则：

- `video/audio/image/subtitle` 类 artifact 必须有 `uri`，最好有 `sha256`。
- 小 JSON payload 可以存在 `payload`，但仍必须写 schema_version。
- immutable artifact 创建后不得原地修改，只能创建新 artifact。
- 删除文件前必须检查是否仍被 active run / finished video / publish package 引用。

### 5.8 MediaInfo

```python
class MediaInfo(BaseModel):
    media_type: Literal["video", "audio", "image", "subtitle", "json"]
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
```

### 5.9 ProviderInvocation

```python
class ProviderInvocation(BaseModel):
    id: str
    run_id: str | None
    node_run_id: str | None
    case_id: str | None
    capability: str
    provider_id: str
    model_id: str
    provider_profile_id: str
    prompt_version_id: str | None = None
    status: ProviderStatus
    usage: UsageMeterRecord | None = None
    price_item_id: str | None = None
    estimated_cost: Money | None = None
    actual_cost: Money | None = None
    billing_status: Literal["estimated", "reconciled", "unpriced", "ignored"] = "estimated"
    request_artifact_id: str | None = None
    response_artifact_id: str | None = None
    external_job_id: str | None = None
    error: ProviderError | None = None
    started_at: datetime
    finished_at: datetime | None = None
```

### 5.10 FinishedVideo / PublishPackage

```python
class FinishedVideo(BaseModel):
    id: str
    case_id: str
    job_id: str
    run_id: str
    title: str
    script_snapshot: str
    video_artifact: ArtifactRef
    cover_artifact: ArtifactRef | None = None
    subtitle_artifact: ArtifactRef | None = None
    duration_sec: float
    production_summary: dict[str, Any]
    qc_status: Literal["pending", "passed", "failed", "manual_required"] = "pending"
    created_at: datetime

class PublishPackage(BaseModel):
    id: str
    case_id: str | None
    source_type: Literal["finished_video", "upload"]
    source_finished_video_id: str | None = None
    video_artifact: ArtifactRef
    cover_artifact: ArtifactRef | None = None
    title: str
    description: str
    tags: list[str]
    platform_defaults: PublishDefaults
    created_at: datetime
```

Publishing 只能消费 `FinishedVideo`、`PublishPackage` 或用户上传媒体。不得读 production debug metadata。

---

## 6. Workflow 执行语义

### 6.1 WorkflowTemplate

```python
class WorkflowTemplate(BaseModel):
    id: str
    version: str
    nodes: list[NodeSpec]
    edges: list[WorkflowEdge]
    default_retry_policy: RetryPolicy

class NodeSpec(BaseModel):
    node_id: str
    node_version: str
    implementation: str
    input_schema: str
    output_schema: str
    retry_policy: RetryPolicy | None = None
    resume_policy: ResumePolicy
    side_effects: list[Literal["provider_call", "ledger_commit", "external_upload", "publish_attempt"]] = []
```

### 6.2 canonical input hash

`input_manifest_hash` 必须由 canonical JSON 生成：

- 字段按 key 排序。
- 移除时间戳、trace、progress、debug 字段。
- Artifact 只用 `artifact_id + kind + schema_version + sha256`。
- Provider profile 参与 hash，profile 版本变化必须导致重跑。
- Prompt version 参与 hash。
- Node version 参与缓存判断，但不进入 input hash 本身。

### 6.3 Resume Contract

续跑必须创建新 run。

新 run 允许复用旧 artifact 仅当全部成立：

1. `node_id` 相同。
2. `node_version` 相同。
3. `input_manifest_hash` 相同。
4. artifact 文件存在。
5. sha256 校验通过。
6. artifact kind 与 schema_version 匹配当前 workflow。

副作用节点规则：

- Provider call 不自动重放。
- Ledger commit 不自动重放。
- Publish attempt 不自动重放。
- External upload 不自动重放。

如果副作用节点要 resume，必须声明 idempotency key。

### 6.4 Retry Contract

重试分两种：

- Retry run：新 run，从头执行，可复用缓存 artifact，但不保证跳到失败节点。
- Resume run：新 run，复用连续合法 artifact 前缀，从第一个不合法节点继续。

### 6.5 Cancel Contract

取消必须：

- 标记 run cancelling。
- 让正在运行的 node 收到 cancel token。
- 如果 provider 支持 cancel，调用 provider cancel。
- 如果 provider 不支持 cancel，标记本地 cancelled，但 provider 结果回来后不得进入生产成片。

### 6.6 Selection Ledger reservation

素材/BGM/字体选择要避免并发任务撞同一资源。必须实现：

```text
reserve -> commit -> release/expire
```

规则：

- Planning 阶段先 reserve。
- 生产成功到相关节点后 commit。
- Run 失败或取消时，按策略保留或释放。
- Reservation 有 TTL。
- 失败任务默认保留用于多样性记忆，但可以在 ops 中清理。

---

## 7. 视频生产 Workflow 节点契约

### 7.1 节点总览

```text
ValidateRequest
LoadCaseContext
ResolveCreativeIntent
TTS
MaterialPackPlanning
NarrationAlignment
PortraitPlanning
BrollPlanning
StylePlanning
TimelinePlanning
PortraitTrackBuild
LipSync
RenderFinalTimeline
SubtitleAndBgmMix
ExportFinishedVideo
FinalizeRunReport
```

### 7.2 ValidateRequestNode

输入：

- `DigitalHumanVideoRequest`

输出：

- `ValidatedProductionSpec` artifact

必须校验：

- case 存在。
- script 非空。
- voice 可用。
- provider profile 存在且 capability 匹配。
- 指定 template/BGM/font/cover 存在。
- request 与 workflow template 兼容。

错误：

- `validation.missing_case`
- `validation.missing_voice`
- `provider.unsupported_option`

### 7.3 LoadCaseContextNode

输入：

- case_id
- 当前 request

输出：

- `case.context` artifact

内容：

- Case profile。
- 历史脚本摘要。
- 历史视频摘要。
- 发布表现摘要。
- active case memories。
- 近期 reflection runs。
- 素材/选择历史。

不得：

- 生成新脚本。
- 修改 memory。

### 7.4 ResolveCreativeIntentNode

输入：

- request.script
- case.context
- 可选 semantic_pack

输出：

- `creative.intent` artifact

要求：

- 如果 request 带 intent，校验并复用。
- 否则通过 Prompt Registry 渲染 prompt 调 LLM。
- 输出必须 schema 校验。

### 7.5 TTSNode

输入：

- script
- voice options
- provider profile

输出：

- `audio.tts`
- 可选 `audio.alignment.raw`

错误：

- provider timeout / quota / auth / remote failed。

### 7.6 MaterialPackPlanningNode

输入：

- case.context
- creative.intent
- request options
- selection ledger

输出：

- `plan.material_pack`

内容：

- portrait candidates
- broll candidates
- font candidates
- bgm candidates
- missing material diagnostics
- reservation ids

错误：

- portrait 无可用素材：如果后续 portrait 必需，可先 warning；真正 hard fail 由 PortraitPlanning 决定。

### 7.7 NarrationAlignmentNode

输入：

- `audio.tts`
- script

输出：

- `audio.alignment`
- `narration.units`

策略：

1. TTS subtitle。
2. forced alignment。
3. ASR。
4. strict 模式下不允许估算 fallback。

### 7.8 PortraitPlanningNode

输入：

- narration.units
- material_pack.portrait
- creative.intent
- rhythm preset

输出：

- `plan.portrait`

硬失败：

- 不能覆盖完整音频。
- source window 不足。
- timeline 不可合法化。

错误：

- `material.insufficient.portrait`

### 7.9 BrollPlanningNode

输入：

- narration.units
- material_pack.broll
- creative.intent
- max inserts

输出：

- `plan.broll`

策略：

- B-roll 不足是 soft degrade，输出 empty plan。
- 必须写 skipped_reason。

### 7.10 StylePlanningNode

输入：

- creative.intent
- material_pack.font / bgm
- user override

输出：

- `plan.style`

要求：

- 用户手动指定优先。
- 自动选择必须 reserve/commit ledger。
- 不得随机选择。

### 7.11 TimelinePlanningNode

输入：

- portrait plan
- broll plan
- style plan
- narration units

输出：

- `plan.timeline`
- `plan.render`

必须做：

- 统一量化到 30fps。
- 校验无重叠、无负时长、无越界。
- 输出 validation report。

错误：

- `render.invalid_timeline`

### 7.12 PortraitTrackBuildNode

输入：

- portrait plan
- portrait asset refs

输出：

- `video.portrait_track`

要求：

- 按帧精确切片。
- concat 后校验 duration。
- source window 不得越界。

### 7.13 LipSyncNode

输入：

- `video.portrait_track`
- `audio.tts`
- lipsync options

输出：

- `video.lipsync`
- lipsync report

如果 disabled：

- 输出 pass-through `video.lipsync`。
- status 为 skipped。

### 7.14 RenderFinalTimelineNode

输入：

- `video.lipsync`
- `plan.render`
- B-roll assets

输出：

- `video.rendered`

要求：

- 不烧字幕。
- 不混 BGM。
- 只负责画面 timeline。

### 7.15 SubtitleAndBgmMixNode

输入：

- `video.rendered`
- `audio.tts`
- `plan.style`

输出：

- `video.final`
- `subtitle.ass`

策略：

- 字幕失败是 render failure，除非用户关闭字幕。
- BGM 不可用按 policy soft degrade。

### 7.16 ExportFinishedVideoNode

输入：

- `video.final`
- run metadata

输出：

- `video.finished`
- `cover.image`
- `publish.package`
- `FinishedVideo` record

要求：

- 写 OSS/local artifact。
- 生成缩略图。
- 创建 FinishedVideo。

### 7.17 FinalizeRunReportNode

输入：

- all node_runs
- artifacts
- provider invocations

输出：

- `run.report.public`
- `run.report.debug`

要求：

- public report 给前端。
- debug report 给工程和 ops。
- 前端不得直接读 debug report 除非进入调试模式。

---

## 8. Case 自进化与数据反馈闭环

### 8.1 核心目标

Agent 进入一个 case 后，必须能读取：

- 过去脚本。
- 过去成片。
- 过去发布记录。
- 各平台表现数据。
- 素材使用记录。
- 剪辑计划。
- 封面/标题/文案。
- 过去复盘。
- 已审核长期记忆。

然后 Agent 需要把这些变成下一轮创作策略，而不是从零写脚本。

### 8.2 闭环链路

```text
Case Context
  -> Historical Scripts / Videos / Metrics / Memories
  -> Strategy Planning
  -> Script Generation
  -> Video Production
  -> Publish
  -> Metric Ingestion
  -> Performance Attribution
  -> Reflection
  -> Memory Commit
  -> Next Generation
```

### 8.3 数据模型

```python
class ScriptVersion(BaseModel):
    id: str
    case_id: str
    source: Literal["manual", "agent", "imported"]
    content: str
    title: str | None
    creative_intent_artifact_id: str | None
    generated_by_run_id: str | None
    parent_script_id: str | None = None
    created_at: datetime

class VideoVersion(BaseModel):
    id: str
    case_id: str
    script_version_id: str
    finished_video_id: str
    run_id: str
    timeline_plan_artifact_id: str
    style_plan_artifact_id: str
    created_at: datetime

class PublishRecord(BaseModel):
    id: str
    case_id: str
    video_version_id: str
    platform: str
    account_id: str | None
    publish_batch_id: str | None
    title: str
    description: str
    cover_artifact_id: str | None
    published_at: datetime | None
    status: str

class PerformanceObservation(BaseModel):
    id: str
    case_id: str
    video_version_id: str
    publish_record_id: str
    platform: str
    account_id: str | None
    observed_at: datetime
    window: Literal["1h", "24h", "3d", "7d", "30d"]
    impressions: int | None = None
    views: int | None = None
    avg_watch_sec: float | None = None
    completion_rate: float | None = None
    like_rate: float | None = None
    comment_rate: float | None = None
    share_rate: float | None = None
    follow_rate: float | None = None
    conversion_count: int | None = None
    raw_metrics: dict[str, Any] = {}

class CreativeFeatureVector(BaseModel):
    id: str
    case_id: str
    script_version_id: str
    video_version_id: str | None
    hook_type: str | None
    script_structure: str | None
    topic_tags: list[str]
    duration_sec: float | None
    broll_density: float | None
    cut_density: float | None
    subtitle_style_id: str | None
    bgm_id: str | None
    cover_style: str | None
    cta_type: str | None
    material_ids: list[str] = []

class CaseMemoryScope(BaseModel):
    applies_to_case_ids: list[str] = []
    applies_to_script_intents: list[str] = []
    applies_to_platforms: list[str] = []
    applies_to_audience_segments: list[str] = []
    excluded_case_ids: list[str] = []
    valid_from: datetime | None = None
    valid_until: datetime | None = None

class CaseMemory(BaseModel):
    id: str
    case_id: str
    memory_type: Literal["script_pattern", "video_pattern", "audience_insight", "editing_rule", "negative_lesson"]
    statement: str
    evidence_refs: list[str]
    confidence: float
    sample_size: int
    scope: CaseMemoryScope
    status: Literal["proposed", "approved", "active", "deprecated", "rejected"]
    created_by_reflection_run_id: str
    supersedes_memory_id: str | None = None
    created_at: datetime
    updated_at: datetime

class ReflectionRun(BaseModel):
    id: str
    case_id: str
    input_observation_ids: list[str]
    input_feature_vector_ids: list[str]
    report_artifact_id: str
    memory_proposal_ids: list[str]
    status: Literal["running", "completed", "failed"]
    created_at: datetime
```

### 8.4 自进化节点

#### LoadCaseContextNode

在脚本生成和视频生产前都可调用。

输出 `case.context`：

- case profile
- active memories
- recent scripts/videos
- performance summary
- negative lessons
- current experiment assignments

#### HistoricalPerformanceAnalysisNode

输入：

- PerformanceObservation
- CreativeFeatureVector
- VideoVersion / ScriptVersion lineage

输出：

- `case.performance_analysis`

要求：

- 不能把播放量直接当质量。
- 必须按平台、账号、发布时间窗口分组。
- 必须标 sample_size。

#### CaseReflectionNode

输入：

- performance analysis
- case memories

输出：

- `case.reflection`
- memory proposals

每条结论必须包含：

- evidence refs
- confidence
- sample size
- counter examples
- scope

#### CaseMemoryCommitNode

输入：

- memory proposals
- approval policy

输出：

- active/proposed/deprecated memories

规则：

- 单条爆款不能直接写 active memory。
- 默认进入 proposed。
- 支持人工审核。
- 支持 supersede 旧记忆。

#### ScriptStrategyPlanningNode

输入：

- case.context
- active memories
- 当前创作目标

输出：

- `script.strategy`

要求：

- 明确列出本轮采用哪些 case memories。
- 明确列出规避哪些 negative lessons。
- 给后续 script generation 使用。

### 8.5 反相关风险控制

系统必须区分：

- observation：观察到的数据。
- correlation：相关性。
- hypothesis：待验证假设。
- approved memory：经过审核的长期记忆。

不能把 correlation 直接变成 approved memory。

### 8.6 Case 自进化 API

- `GET /api/cases/{case_id}/knowledge`
- `GET /api/cases/{case_id}/memory`
- `POST /api/cases/{case_id}/memory/{memory_id}/approve`
- `POST /api/cases/{case_id}/memory/{memory_id}/reject`
- `GET /api/cases/{case_id}/performance`
- `POST /api/cases/{case_id}/metrics/import`
- `POST /api/cases/{case_id}/reflection-runs`
- `GET /api/cases/{case_id}/insights`
- `GET /api/cases/{case_id}/creative-patterns`
- `POST /api/cases/{case_id}/scripts/generate-with-memory`
- `GET /api/videos/{video_version_id}/performance-attribution`

### 8.7 Case 自进化验收

任意 Case 生产并发布至少 5 条视频后，系统应能回答：

- 哪些脚本结构表现更好。
- 哪些开头/标题/封面表现更好。
- 哪些素材或剪辑风格表现更好。
- 哪些结论只是观察，哪些已写入长期记忆。
- 下一条脚本生成具体采用了哪些历史经验。

---

## 9. 运营中台、成本监控、成品率治理

### 9.1 目标

运营中台必须覆盖：

- API 成本。
- Provider 用量。
- Provider 余额/配额。
- 成品率。
- 失败率。
- QC / 人工审核。
- Prompt 版本。
- 告警。
- 审计。

它不是 debug 页面，而是生产管理面。

### 9.2 数据表

必须实现：

- `provider_price_catalogs`
- `provider_price_items`
- `provider_invocations`
- `usage_meter_records`
- `cost_rollups`
- `budgets`
- `ops_alert_rules`
- `ops_alert_events`
- `production_quality_checks`
- `yield_funnel_events`
- `failure_taxonomy`
- `audit_events`
- `approval_requests`

### 9.3 价格表

```python
class ProviderPriceItem(BaseModel):
    id: str
    catalog_id: str
    provider_id: str
    model_id: str
    capability: str
    unit: Literal["token_input", "token_output", "audio_second", "video_second", "image", "job", "credit"]
    unit_price: Decimal
    currency: str
    effective_from: datetime
    effective_to: datetime | None
    tier: dict[str, Any] | None = None
```

Provider invocation 找不到有效 price item 时：

- billing_status = `unpriced`
- 触发告警
- 可按环境策略阻止生产调用

### 9.4 成本指标

必须定义：

- `estimated_cost`
- `actual_cost`
- `unit_cost_per_finished_video`
- `unit_cost_per_qc_passed_video`
- `unit_cost_per_published_video`
- `provider_cost`
- `model_cost`
- `prompt_version_cost`
- `wasted_cost`
- `retry_cost`
- `cost_variance`

### 9.5 成品率漏斗

`yield_funnel_events` 必须记录：

```text
submitted
admitted
started
node_started
node_succeeded
node_failed
finished_video_created
qc_started
qc_passed
qc_failed
manual_approved
manual_rejected
publish_started
published
publish_failed
```

成品率不得只看 workflow succeeded。

必须计算：

- technical_success_rate
- finished_video_rate
- qc_pass_rate
- approval_pass_rate
- publish_success_rate
- true_yield_rate
- rework_rate
- discard_rate
- stage_pass_rate
- provider_success_rate
- prompt_version_yield

### 9.6 质量与失败分类

failure taxonomy 至少包括：

- provider_error
- provider_timeout
- quota_exceeded
- price_missing
- prompt_render_error
- prompt_output_invalid
- material_insufficient
- timeline_invalid
- render_failed
- subtitle_failed
- bgm_failed
- lipsync_quality_failed
- qc_failed
- publish_failed
- manual_rejected

技术成功但 QC 不通过，不能计入 true yield。

### 9.7 Ops 页面

必须有：

- 运营总览
- 成本中心
- API 价格管理
- Provider 用量与余额
- 成品率看板
- 失败分析
- Prompt Registry
- Prompt 发布/回滚
- Prompt 效果分析
- 告警中心
- 审计日志

### 9.8 告警

必须支持：

- 预算超限。
- 单片成本异常。
- Provider 余额低。
- Provider 失败率突增。
- 价格表缺失或过期。
- 账单对账偏差。
- 成品率下降。
- QC 不通过率升高。
- 重试成本异常。
- Prompt 新版本效果劣化。
- 未审批 prompt/价格/provider 配置进入生产。
- 审计日志写入失败。

---

## 10. Prompt Registry 与 Prompt Ops

### 10.1 规则

生产 prompt 不允许写在节点代码里。所有生产 prompt 必须进入 Prompt Registry。

### 10.2 数据模型

```python
class PromptTemplate(BaseModel):
    id: str
    name: str
    purpose: str
    owner: str
    default_output_schema: str
    created_at: datetime

class PromptVersion(BaseModel):
    id: str
    template_id: str
    version: str
    content: str
    content_hash: str
    variables_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: Literal["draft", "reviewing", "approved", "published", "deprecated", "rolled_back"]
    author: str
    approved_by: str | None
    published_at: datetime | None
    rollback_of_version_id: str | None = None

class PromptBinding(BaseModel):
    id: str
    prompt_template_id: str
    prompt_version_id: str
    node_id: str | None
    capability: str | None
    provider_profile_id: str | None
    case_id: str | None
    environment: Literal["dev", "staging", "prod"]

class PromptInvocation(BaseModel):
    id: str
    prompt_template_id: str
    prompt_version_id: str
    run_id: str | None
    node_run_id: str | None
    provider_invocation_id: str | None
    variables_hash: str
    rendered_input_hash: str
    output_validation_status: Literal["passed", "failed", "skipped"]
    error_code: str | None
    created_at: datetime
```

### 10.3 Prompt 发布流程

```text
draft -> reviewing -> approved -> published -> deprecated
published -> rolled_back
```

规则：

- prod 只能使用 published prompt。
- prompt 变更必须可 diff。
- prompt version 必须能回滚。
- prompt binding 必须可按 case / provider / node 灰度。
- prompt 效果必须按成本、失败率、成品率、返工率归因。

---

## 11. Provider 插件与 Secrets / Quota

### 11.1 Capability 类型

所有 provider 统一走 capability：

- `llm.chat`
- `vlm.annotation`
- `tts.speech`
- `asr.transcribe`
- `lipsync.video`
- `image.generate`
- `image.edit`

### 11.2 ProviderProfile

```python
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

class ProviderOptionsSchemaRef(BaseModel):
    schema_id: str
    schema_version: str
    dialect: Literal["json_schema_2020_12", "pydantic"]
    sha256: str

class ProviderProfile(BaseModel):
    id: str
    provider_id: str
    model_id: str
    capability: str
    display_name: str
    environment: Literal["local", "dev", "staging", "prod"]
    secret_ref: str | None = None
    enabled: bool
    concurrency_key: str
    timeout_sec: int
    retry_policy: RetryPolicy
    cost_policy_id: str | None
    options_schema_ref: ProviderOptionsSchemaRef
    default_options: dict[str, JsonValue] = {}
    version: str
```

规则：

- `options_schema_ref` 是 provider settings 表单、adapter 参数校验、workflow input hash 的唯一 schema 来源。
- `default_options` 保存前必须按 `options_schema_ref` 校验；校验后的 canonical JSON 参与 workflow input hash。
- `secret_ref` 可为空，仅限不需要密钥的 sandbox/mock provider。
- prod provider profile 必须引用 enabled SecretRecord。

### 11.3 Secrets

```python
class SecretStatus(str, Enum):
    active = "active"
    disabled = "disabled"
    rotated = "rotated"

class SecretRecord(BaseModel):
    id: str
    secret_ref: str
    display_name: str
    provider_id: str | None = None
    account_group: str | None = None
    environment: Literal["local", "dev", "staging", "prod"]
    status: SecretStatus
    created_by: str
    created_at: datetime
    rotated_from_secret_id: str | None = None
    disabled_at: datetime | None = None

class CreateSecretRequest(BaseModel):
    display_name: str
    provider_id: str | None = None
    account_group: str | None = None
    environment: Literal["local", "dev", "staging", "prod"]
    plaintext_secret: str

class RotateSecretRequest(BaseModel):
    plaintext_secret: str
    reason: str

class SecretPreview(BaseModel):
    id: str
    display_name: str
    provider_id: str | None
    account_group: str | None
    environment: Literal["local", "dev", "staging", "prod"]
    status: SecretStatus
    created_at: datetime
    disabled_at: datetime | None = None
```

API：

- `GET /api/secrets`
- `POST /api/secrets`
- `POST /api/secrets/{secret_id}/rotate`
- `PATCH /api/secrets/{secret_id}/disable`

规则：

- API key 不写 DB 明文。
- DB 只存 `secret_ref` 和 `SecretRecord` 元数据。
- API 永不返回明文或可逆密文。
- 支持按 environment / provider / account group 配置。
- 创建、读取、轮换、禁用 secret 的操作全部写 audit。
- 轮换后新 ProviderInvocation 必须使用新 secret；已运行中的 invocation 不被追溯改写。
- disable secret 后，引用它的 prod ProviderProfile 必须自动变为不可调度并触发告警。

### 11.4 Quota / Concurrency

必须支持：

- provider global concurrency。
- case-level budget。
- daily/monthly quota。
- provider balance poll。
- quota exceeded 错误映射。

### 11.5 Sandbox Provider

每个 capability 必须有 mock/sandbox provider，用于测试和本地开发。

---

## 12. Annotation 架构

### 12.1 分层

```text
Canonical Annotation
  -> UI Projection
  -> Search Projection
  -> Material Planning Projection
  -> Reporting Projection
```

### 12.2 Ownership

- Analyzer 只写 canonical annotation。
- ProjectionBuilder 从 canonical 重建 projection。
- Indexer 从 canonical/projection 重建 DB index。
- UI 只能提交 patch。
- PatchService 合并 patch 后生成新 canonical version。

### 12.3 全新标注策略

v3 不读取旧 `annotation_v3` 槽，也不要求理解旧标注文件。所有素材进入新系统时必须：

- 先生成 `MediaAsset`。
- 再按 `annotation_v4` canonical schema 重新标注。
- 标注失败的素材进入 `annotation_failed`，不得进入可用池。
- 人工 patch 只通过 AnnotationEditView 写入新 canonical version。

---

## 13. Publishing 边界

Publishing 只接收：

- `FinishedVideo`
- `PublishPackage`
- user uploaded media

发布流程：

```text
PublishPackage
  -> Normalize
  -> ASR / Copy Generation
  -> Cover
  -> Manual Review
  -> Publish Attempt
  -> Publish Result
  -> Metrics Ingestion
```

发布中心不得读取：

- production debug report
- internal node metadata
- task metadata

---

## 14. 数据库最低表结构

实现必须使用 Postgres 16+。本地和测试环境通过 docker-compose 启动 Postgres，不提供其他数据库 adapter。

最低表：

- `users`
- `sessions`
- `registration_codes`
- `cases`
- `case_agent_runs`
- `case_agent_source_bindings`
- `creative_briefs`
- `creative_intent_candidates`
- `script_drafts`
- `memory_proposals`
- `jobs`
- `workflow_runs`
- `node_runs`
- `artifacts`
- `upload_sessions`
- `secret_records`
- `provider_profiles`
- `provider_invocations`
- `usage_meter_records`
- `prompt_templates`
- `prompt_versions`
- `prompt_bindings`
- `prompt_invocations`
- `prompt_experiments`
- `prompt_experiment_assignments`
- `media_assets`
- `annotations`
- `annotation_projections`
- `selection_ledger`
- `selection_reservations`
- `finished_videos`
- `publish_packages`
- `publish_batches`
- `publish_attempts`
- `script_versions`
- `video_versions`
- `publish_records`
- `performance_observations`
- `creative_feature_vectors`
- `case_memories`
- `reflection_runs`
- `yield_funnel_events`
- `production_quality_checks`
- `provider_price_catalogs`
- `provider_price_items`
- `cost_rollups`
- `budgets`
- `ops_alert_rules`
- `ops_alert_events`
- `failure_taxonomy`
- `approval_requests`
- `exchange_rates`
- `audit_events`
- `outbox_events`
- `import_batches`
- `import_id_mappings`

约束：

- 所有表必须有主键。
- 所有跨实体引用必须有外键，并在 repository 层做显式校验与错误映射。
- `artifacts` immutable。
- `node_runs(run_id, node_id, attempt)` 建索引。
- `provider_invocations(case_id, provider_id, model_id, started_at)` 建索引。
- `performance_observations(case_id, video_version_id, window)` 建唯一或去重索引。
- `selection_reservations` 有 TTL 索引。

入口表最低字段：

```python
class SessionRow(BaseModel):
    id: str
    user_id: str
    status: Literal["active", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    ip_hash: str | None = None
    user_agent_hash: str | None = None

class RegistrationCodeRow(BaseModel):
    id: str
    code_hash: str
    role: Literal["admin", "operator", "viewer"]
    max_uses: int | None = None
    used_count: int = 0
    status: Literal["active", "disabled", "expired"]
    expires_at: datetime | None = None
    created_by: str
    created_at: datetime

class UploadSessionRow(BaseModel):
    id: str
    kind: UploadKind
    case_id: str | None
    status: UploadSessionStatus
    object_key: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    created_by: str
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None

class ImportBatchRow(BaseModel):
    id: str
    import_type: str
    status: Literal["created", "running", "completed", "failed", "partially_failed"]
    dry_run: bool
    idempotency_key: str | None
    rows_artifact_id: str | None = None
    created_by: str
    created_at: datetime
    finished_at: datetime | None = None

class ImportIdMappingRow(BaseModel):
    id: str
    import_batch_id: str
    entity_type: str
    external_id: str
    internal_id: str
    created_at: datetime
```

---

## 15. API 契约

### 15.1 通用规则

- 所有列表接口支持 `limit` / `cursor`。
- 所有写接口支持 `Idempotency-Key`。
- 所有响应包含 `request_id`。
- 所有错误用统一 error body。
- 管理接口需要 admin 权限。

### 15.2 核心 API

Jobs / Runs：

- `POST /api/jobs/digital-human-video`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/runs`
- `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/cancel`
- `POST /api/runs/{run_id}/retry`
- `POST /api/runs/{run_id}/resume`
- `GET /api/runs/{run_id}/report`
- `GET /api/runs/{run_id}/artifacts`
- `GET /api/runs/{run_id}/events`

Cases：

- `GET /api/cases`
- `POST /api/cases`
- `GET /api/cases/{case_id}`
- `PATCH /api/cases/{case_id}`
- `GET /api/cases/{case_id}/knowledge`
- `GET /api/cases/{case_id}/memory`
- `GET /api/cases/{case_id}/performance`
- `GET /api/cases/{case_id}/insights`

Media：

- `POST /api/media/assets`
- `GET /api/media/assets`
- `GET /api/media/assets/{asset_id}`
- `POST /api/annotations/{asset_id}/rerun`
- `GET /api/annotations/{asset_id}`
- `PATCH /api/annotations/{asset_id}`

Publishing：

- `POST /api/publish/packages`
- `POST /api/publish/batches`
- `GET /api/publish/batches`
- `GET /api/publish/batches/{batch_id}`
- `POST /api/publish/batches/{batch_id}/submit`

Ops：

- `GET /api/ops/dashboard`
- `GET /api/ops/cost-rollups`
- `GET /api/ops/yield-funnel`
- `GET /api/ops/budgets`
- `POST /api/ops/budgets`
- `PATCH /api/ops/budgets/{budget_id}`
- `POST /api/ops/alerts/{event_id}/ack`
- `POST /api/ops/alerts/{event_id}/resolve`
- `GET /api/audit/events`

Prompts：

- `GET /api/prompts`
- `POST /api/prompts`
- `GET /api/prompts/{template_id}/versions`
- `POST /api/prompts/{template_id}/versions`
- `POST /api/prompts/{template_id}/versions/{version_id}/approve`
- `POST /api/prompts/{template_id}/versions/{version_id}/publish`
- `POST /api/prompts/{template_id}/rollback`

Providers：

- `GET /api/providers/capabilities`
- `GET /api/providers/profiles`
- `POST /api/providers/profiles`
- `GET /api/providers/price-catalogs`
- `POST /api/providers/price-catalogs`
- `GET /api/providers/usage`

### 15.3 WebSocket event

```python
class RunEvent(BaseModel):
    event_id: str
    run_id: str
    job_id: str
    event_type: Literal["run_update", "node_update", "artifact_created", "warning", "error"]
    node_id: str | None = None
    status: str | None = None
    progress: float | None = None
    message: str
    created_at: datetime
```

---

## 16. 前端页面与 ViewModel

### 16.1 路由

- `/login`
- `/studio`
- `/studio/:caseId`
- `/studio/:caseId/runs`
- `/studio/:caseId/finished-videos`
- `/studio/:caseId/publish`
- `/studio/:caseId/insights`
- `/studio/:caseId/memory`
- `/library/voices`
- `/library/portrait`
- `/library/broll`
- `/library/fonts`
- `/library/bgm`
- `/ops`
- `/ops/costs`
- `/ops/yield`
- `/ops/prompts`
- `/ops/alerts`
- `/ops/audit`
- `/settings`

### 16.2 ViewModel

前端不得直接读 debug metadata。

```ts
type RunCard = {
  runId: string
  jobId: string
  caseId: string
  status: string
  progress: number
  currentNodeLabel?: string
  title: string
  previewUrl?: string
  warnings: string[]
  canResume: boolean
  canRetry: boolean
  canPublish: boolean
}
```

```ts
type CaseInsightCard = {
  insightId: string
  statement: string
  confidence: number
  sampleSize: number
  evidenceCount: number
  status: "observation" | "hypothesis" | "active_memory"
}
```

### 16.3 新前端页面映射

- 旧 Queue 页面替换为 Runs。
- 早期任务详情概念替换为 RunReport。
- PublishCenter 只使用 PublishPackage。
- Annotation editor 使用 AnnotationEditView。
- API client 按领域拆分，不再一个大文件。

---

## 17. 旧概念参考映射（非兼容要求）

本章只帮助实施 Agent 理解旧系统大概对应的新概念。它不是迁移要求，也不是兼容要求。

| 旧概念 | 新概念 | v3 决策 |
|---|---|---|
| Task | Job + WorkflowRun | 只保留产品思想，不导入历史 Task 数据 |
| Task.status/stage/progress | RunStatus + NodeRun | 全新状态机 |
| Task.config | typed request + workflow options | 不兼容旧 config |
| Task.metadata.* | Artifact / RunReport / DebugTrace | 禁止继续大杂烩 metadata |
| stage_artifacts.sqlite3 | artifacts + node_runs | 不导旧库，可重新生成 |
| queue.sqlite3 | jobs + workflow_runs + node_runs | 不导旧库 |
| publish batch JSON | publish_batches tables | 旧批次可人工重新导入视频 |
| workbench cases JSON | cases table | Case 从新系统创建或 CSV 导入 |
| script history JSON | script_versions table | 可按新 CSV/JSON schema 导入 |
| annotation_v3 storage slot | annotations canonical | 不兼容旧槽位；素材重新标注 |
| system_prompts.json | Prompt Registry | Prompt 重新录入、审批、发布 |

原则：只迁移“业务含义”，不迁移“技术债形态”。
---

## 18. 全新导入、上线与回滚策略

### 18.1 导入策略

v3 不要求导入旧仓库内部数据结构。只提供面向新系统标准实体的导入入口：

- Case CSV/JSON 导入。
- ScriptVersion CSV/JSON 导入。
- MediaAsset 批量上传/导入。
- FinishedVideo / VideoVersion / PublishRecord CSV/JSON 导入。
- PerformanceObservation CSV/JSON 导入。
- Prompt seed 导入。
- Provider price catalog 导入。

所有导入都必须走新系统 schema，不读旧 `queue.sqlite3`、旧 stage artifacts、旧 publish batch JSON。

### 18.2 Fresh Import 原则

- 导入前先创建 Case。
- 素材按新 UploadSession 导入，创建新的 Artifact 和 MediaAsset。
- 素材导入后必须重新跑 annotation，不复用旧 annotation。
- 历史脚本可导入为 ScriptVersion。
- 历史成片文件可导入为 FinishedVideo + VideoVersion + PublishRecord，但必须走新 UploadSession / Artifact / schema。
- 历史表现可导入为 PerformanceObservation，但必须显式绑定已存在或同批创建的 video_version_id / publish_record_id；不能靠标题猜。
- Prompt 必须重新进入 Prompt Registry，经过 approve/publish 后才可用于 prod。

### 18.3 Clean Cutover

推荐上线步骤：

1. 新系统独立部署。
2. 创建首批 Case。
3. 按新协议导入素材、脚本、价格表、prompt。
4. 跑 annotation、case context、provider sandbox 测试。
5. 跑 golden cases。
6. 小范围真实生产。
7. 验证 ops dashboard、成本、成品率、case memory。
8. 全量切换用户入口。

### 18.4 回滚

v3 不要求回滚到旧系统并保持数据连续。

如果新系统上线后需要回退：

- 停止新系统入口。
- 导出新系统已产出的 FinishedVideo、PublishRecord、MediaAsset 文件和 CSV 清单。
- 业务上可人工转移成品，不要求写回旧数据库。
- Workflow internals、NodeRun、Artifact lineage 不回写旧系统。

### 18.5 导入验收

全新导入只验收新系统实体：

- Case 可进入工作台。
- MediaAsset 可预览、可标注。
- ScriptVersion 可用于生成视频。
- FinishedVideo / VideoVersion / PublishRecord 可进入 Case insight lineage。
- Prompt Registry 有 published prompt。
- Provider profiles 和 price catalog 可用。
- First golden run 成功产出 FinishedVideo。
---

## 19. 部署、配置与 Secrets

### 19.1 进程

- `api`
- `worker`
- `web`
- `temporal-server`
- `temporal-worker`
- `temporal-postgres`
- `postgres`
- `minio` 或生产 ObjectStore
- `redis` 可选
- `connectors/oceanengine` 独立运行

### 19.2 环境

必须支持：

- local
- dev
- staging
- prod

### 19.3 配置文件

```text
configs/
  provider_profiles.yaml
  workflow_templates.yaml
  artifact_retention.yaml
  ops_alert_rules.yaml
  prompt_seed/
```

### 19.4 Secrets

- 本地可用 `.env.local`。
- 生产必须用 secret manager 或加密存储。
- secret_ref 不可直接泄露给前端。

---

## 20. 测试与验收

### 20.1 测试目录

```text
tests/
  contract/
  api/
  nodes/
  providers/
  workflows/
  golden/
  import/
  frontend/
```

### 20.2 Golden Cases

至少 12 条：

1. 最小成功视频：脚本 + voice + portrait。
2. 启用 B-roll 成功。
3. B-roll 不足 soft degrade。
4. BGM 无可用标注 soft degrade。
5. 人像素材不足 hard fail。
6. HeyGem 超时后 resume。
7. Provider quota exceeded。
8. Timeline 越界被拒绝。
9. 字幕开启成功。
10. 剪映草稿导出成功。
11. 从 FinishedVideo 创建发布批次。
12. 发布失败后 retry publish。
13. Fresh import：Case + ScriptVersion + MediaAsset 导入后可在新前端展示。
14. Fresh imported MediaAsset 重新 annotation 后可打开 Annotation Editor 并保存 patch。
15. Fresh imported FinishedVideo / PublishRecord / PerformanceObservation 能进入 Case insights。
16. Case 发布 5 条后生成 reflection 和 memory proposal。

### 20.3 Provider Contract Tests

每个 provider 都必须测：

- capability schema。
- option validation。
- secret missing。
- quota exceeded。
- timeout。
- remote failed。
- cost metering。
- sandbox provider。

### 20.4 Prompt Tests

- prompt render 变量完整性。
- output schema validation。
- prompt version publish/rollback。
- prompt invocation 关联 provider invocation。

### 20.5 Ops Tests

- price missing 告警。
- cost rollup。
- yield funnel。
- QC failed 不计入 true yield。
- prompt 新版本劣化告警。

### 20.6 最终验收

另一个 Agent 实施完成后，必须证明：

1. 新增 lip-sync provider 不改 production pipeline。
2. 新增 annotation 字段不破坏 UI/search/material planning。
3. 失败 run 可 resume，并复用合法 artifact。
4. 每条视频可追溯脚本、素材、模型、prompt、成本、节点产物。
5. Case 能基于历史表现生成 memory proposal。
6. Ops 能看到成本、成品率、失败率和 prompt 版本表现。
7. Publish 不依赖 production debug metadata。
8. 新素材/脚本/表现数据可按新 schema 导入，新前端可展示导入后的成片与 case 记忆。

---

## 21. 实施顺序

推荐顺序：

1. 建 core contracts、状态机、错误码。
2. 建 DB schema 和 repository。
3. 建 ArtifactStore / ObjectStore。
4. 建 WorkflowRun / NodeRun runtime。
5. 建 ProviderGateway + sandbox providers。
6. 建 Prompt Registry。
7. 建 DigitalHumanVideo workflow 的前 5 个节点。
8. 建 render/lipsync/export 节点。
9. 建 FinishedVideo / PublishPackage / Publishing。
10. 建 Case Knowledge / Performance / Memory。
11. 建 Ops Dashboard。
12. 建 fresh importers。
13. 建 frontend。
14. 跑 golden cases。
15. Cutover。

---

## 22. 第二轮 subagent 审稿记录

第一轮 4 个 subagent 发现的问题已纳入本版：

- Case 自进化不是一等架构目标：已新增第 8 章。
- 成本/成品率/prompt 管理不是运营中台：已新增第 9、10 章。
- 契约太松：已新增第 4、5、6、7、15 章。
- 直接实施会丢旧能力：已新增第 2、17、18、20 章。

本文件应作为重写施工图。若后续 reviewer 仍发现阻塞点，应继续补到本文件，而不是另开口头说明。

---

## 23. 阻塞点补齐附录 A：仍被引用的核心类型

本章补齐前文引用但未定义的类型。实施 Agent 必须先实现本章类型，再写业务模块。

### 23.1 Money

```python
class Money(BaseModel):
    amount: Decimal
    currency: str = Field(..., min_length=3, max_length=3)  # ISO 4217, e.g. CNY/USD
    amount_micro: int | None = None  # 可选，避免浮点误差；1 unit = 1_000_000 micro
```

规则：

- DB 中必须存 `amount_micro` 和 `currency`。
- API 可以返回 `amount` 字符串。
- 不同币种不得直接相加，必须先用汇率表折算。

### 23.2 UsageMeterRecord

```python
class UsageMeterRecord(BaseModel):
    id: str
    provider_invocation_id: str
    provider_id: str
    model_id: str
    capability: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    audio_seconds: float = 0
    video_seconds: float = 0
    image_count: int = 0
    provider_credits: Decimal | None = None
    raw_usage: dict[str, Any] = {}
    created_at: datetime
```

多计费单位规则：

- 一次 provider invocation 可产生一个 UsageMeterRecord。
- 如果 provider 返回多段计费，写入 raw_usage，并把可归一化字段填入标准字段。
- CostAttributionService 用标准字段 + price items 计算 estimated_cost。

### 23.3 ProviderError

```python
class ProviderError(BaseModel):
    code: ErrorCode
    provider_error_code: str | None = None
    message: str
    retryable: bool
    raw_error_ref: ArtifactRef | None = None
```

### 23.4 RetryPolicy / ResumePolicy

```python
class RetryPolicy(BaseModel):
    max_attempts: int = Field(1, ge=1, le=10)
    backoff_seconds: float = Field(0, ge=0)
    backoff_multiplier: float = Field(2.0, ge=1.0)
    retryable_error_codes: list[ErrorCode] = []

class ResumePolicy(BaseModel):
    mode: Literal["never", "reuse_if_hash_match", "always_rerun"] = "reuse_if_hash_match"
    reusable_artifact_kinds: list[ArtifactKind] = []
    side_effect_replay: Literal["forbidden", "idempotent_only"] = "idempotent_only"
```

### 23.5 WorkflowEdge

```python
class WorkflowEdge(BaseModel):
    from_node_id: str
    to_node_id: str
    condition: str | None = None  # 只允许引用上游 node status / artifact presence，不允许任意代码
```

### 23.6 ValidatedProductionSpec

```python
class ValidatedProductionSpec(BaseModel):
    request: DigitalHumanVideoRequest
    case_snapshot: dict[str, Any]
    voice_snapshot: dict[str, Any]
    provider_profile_snapshots: dict[str, ProviderProfile]
    resolved_asset_refs: dict[str, ArtifactRef]
    warnings: list[DegradationNotice] = []
```

### 23.7 PublishDefaults / PublishBatchRequest / AnnotationBatchRequest / CaseAgentRunRequest

```python
class PublishDefaults(BaseModel):
    platforms: list[str]
    mode: Literal["immediate", "scheduled"] = "immediate"
    scheduled_at: datetime | None = None
    tags: list[str] = []
    location: str | None = None
    account_group: str | None = None

class PublishBatchRequest(BaseModel):
    case_id: str | None
    source_type: Literal["finished_videos", "upload"]
    finished_video_ids: list[str] = []
    upload_asset_ids: list[str] = []
    defaults: PublishDefaults

class AnnotationBatchRequest(BaseModel):
    case_id: str | None
    asset_ids: list[str]
    force: bool = False
    material_type: Literal["portrait", "broll", "bgm", "font"] | None = None

class CaseAgentRunRequest(BaseModel):
    case_id: str
    goal: Literal["generate_scripts", "reflect", "recollect_sources", "memory_review"]
    source_binding_ids: list[str] = []
    topic_hint: str | None = None
    target_platform: str | None = None
```

### 23.8 ProviderCapability

```python
class ProviderCapability(BaseModel):
    capability: str
    provider_id: str
    model_id: str
    display_name: str
    input_schema_id: str
    output_schema_id: str
    options_schema_id: str
    supports_async_job: bool
    supports_cancel: bool
    max_payload_bytes: int | None = None
    max_duration_sec: float | None = None
    default_timeout_sec: int
```

### 23.9 AnnotationEditView

```python
class AnnotationEditView(BaseModel):
    asset_id: str
    annotation_id: str
    schema_version: str
    timeline_rows: list[AnnotationTimelineRow]
    quality_events: list[QualityEventRow]
    field_metadata: dict[str, FieldUiMetadata]
    etag: str

class AnnotationPatchRequest(BaseModel):
    annotation_id: str
    base_etag: str
    operations: list[dict[str, Any]]  # JSON Patch RFC 6902
    reason: str | None = None
```

---

## 24. 阻塞点补齐附录 B：Artifact Payload Schema Registry

### 24.1 Artifact payload 规则

`Artifact.payload` 允许 JSON，但必须满足：

- `Artifact.kind + schema_version` 能在 `ArtifactSchemaRegistry` 找到 schema。
- 写入前必须校验。
- 下游读取必须按 schema 反序列化，不允许直接当 dict 用。

```python
class ArtifactSchemaRef(BaseModel):
    kind: ArtifactKind
    schema_version: str
    schema_id: str
    pydantic_model_path: str
    json_schema: dict[str, Any]
```

### 24.2 关键 artifact schemas

```python
class CaseContextArtifact(BaseModel):
    case_id: str
    case_profile: dict[str, Any]
    active_memories: list[CaseMemory]
    recent_script_versions: list[ScriptVersion]
    recent_video_versions: list[VideoVersion]
    performance_summary: "PerformanceMetricView"
    negative_lessons: list[CaseMemory]
    knowledge_items: list["CaseKnowledgeItem"]
    generated_at: datetime

class CreativeIntentArtifact(BaseModel):
    scene_type: Literal["hard_ad", "ip_persona"]
    style_hint: str
    density: str
    closing_cta: str
    cover_focus: dict[str, Any]
    overlay_events: list[dict[str, Any]]
    script_features_hint: dict[str, Any] = {}

class MaterialPackArtifact(BaseModel):
    case_id: str
    portrait_candidates: list[dict[str, Any]]
    broll_candidates: list[dict[str, Any]]
    font_candidates: list[dict[str, Any]]
    bgm_candidates: list[dict[str, Any]]
    reservations: list[str] = []
    diagnostics: dict[str, Any] = {}

class NarrationUnit(BaseModel):
    unit_id: str
    text: str
    start: float
    end: float
    confidence: float

class NarrationUnitsArtifact(BaseModel):
    source: Literal["tts_subtitle", "forced_alignment", "asr", "estimated"]
    units: list[NarrationUnit]
    strict: bool
    warnings: list[str] = []

class PortraitSegment(BaseModel):
    segment_id: str
    asset_id: str
    start: float
    end: float
    source_start: float
    source_end: float
    role: str
    unit_ids: list[str]

class PortraitPlanArtifact(BaseModel):
    fps: int
    total_duration: float
    segments: list[PortraitSegment]
    diagnostics: dict[str, Any]

class BrollOverlay(BaseModel):
    overlay_id: str
    asset_id: str
    timeline_start: float
    timeline_end: float
    source_start: float
    source_end: float
    reason: str
    confidence: float

class BrollPlanArtifact(BaseModel):
    enabled: bool
    overlays: list[BrollOverlay]
    skipped_reason: str | None = None

class StylePlanArtifact(BaseModel):
    subtitle: dict[str, Any]
    bgm: dict[str, Any] | None
    font: dict[str, Any] | None
    selection_reservation_ids: list[str] = []

class TimelineTrackSegment(BaseModel):
    track_id: str
    segment_id: str
    asset_ref: ArtifactRef
    timeline_start_frame: int
    timeline_end_frame: int
    source_start_frame: int | None = None
    source_end_frame: int | None = None

class TimelinePlanArtifact(BaseModel):
    fps: int = 30
    total_frames: int
    tracks: list[TimelineTrackSegment]
    validation: dict[str, Any]

class RenderPlanArtifact(BaseModel):
    timeline_artifact_id: str
    render_size: tuple[int, int]
    fps: int
    output_format: str = "mp4"
    tracks: list[TimelineTrackSegment]

class LipSyncReportArtifact(BaseModel):
    provider_invocation_id: str | None
    provider_profile_id: str | None
    skipped: bool = False
    skipped_reason: str | None = None
    input_video_artifact_id: str
    input_audio_artifact_id: str
    output_video_artifact_id: str
    warnings: list[str] = []

class RunPublicReportArtifact(BaseModel):
    run_id: str
    job_id: str
    status: RunStatus
    finished_video_id: str | None
    preview_url: str | None
    warnings: list["DegradationNotice"]
    cost_summary: dict[str, Any]
    node_summaries: list[dict[str, Any]]

class RunDebugReportArtifact(BaseModel):
    run_id: str
    node_runs: list[NodeRun]
    artifacts: list[ArtifactRef]
    provider_invocations: list[ProviderInvocation]
    traces: dict[str, Any]
```

---

## 25. 阻塞点补齐附录 C：Case 自进化硬契约

### 25.1 Lineage 创建时机

必须按以下时机创建 lineage：

| 事件 | 必须创建/更新 |
|---|---|
| 用户手动输入脚本创建视频 Job | 创建 `ScriptVersion(source=manual)`，并把 `script_version_id` 写入 Job |
| Case Agent 生成草稿 | 创建 `ScriptVersion(source=agent)` 或 `ScriptDraft`；用户采用后转 ScriptVersion |
| `ExportFinishedVideoNode` 成功 | 创建 `FinishedVideo` 和 `VideoVersion` |
| 从 FinishedVideo 创建 PublishPackage | 绑定 `source_finished_video_id` |
| 发布任务创建成功 | 创建 `PublishRecord(status=submitted)` |
| 平台确认发布成功 | 更新 `PublishRecord(status=published, external_post_id, published_url)` |
| 指标导入 | 创建 `PerformanceObservation`，必须绑定 `publish_record_id` 和 `video_version_id` |
| Feature extraction 完成 | 创建 `CreativeFeatureVector` |
| Reflection 完成 | 创建 `ReflectionRun` 和 memory proposals |

### 25.2 DigitalHumanVideoRequest 必须绑定 ScriptVersion

扩展：

```python
class DigitalHumanVideoRequest(BaseModel):
    ...
    script_version_id: str | None = None
```

规则：

- 如果 `script_version_id` 为空，Job service 必须先创建 ScriptVersion。
- 如果不为空，`script` 必须与该 ScriptVersion 快照一致，或显式创建新版本。

### 25.3 PublishRecord 补充字段

```python
class PublishRecord(BaseModel):
    ...
    external_post_id: str | None = None
    external_url: str | None = None
    platform_item_id: str | None = None
    published_url: str | None = None
    import_source: Literal["xiaovmao", "platform_api", "oceanengine_rpa", "manual_csv"] | None = None
    raw_payload_artifact_id: str | None = None
```

### 25.4 Metrics import schema

```python
class MetricsImportRequest(BaseModel):
    source: Literal["manual_csv", "oceanengine_rpa", "platform_api"]
    platform: str
    account_id: str | None
    rows: list[dict[str, Any]] | None = None
    file_artifact_id: str | None = None
    matching_policy: Literal["external_post_id", "platform_item_id", "published_url", "strict_manual"] = "external_post_id"

class MetricsImportResponse(BaseModel):
    imported_count: int
    unmatched_count: int
    unmatched_rows_artifact_id: str | None
    observation_ids: list[str]
```

禁止用标题和发布时间猜测匹配，除非 matching_policy 是人工 strict_manual 且导入报告写 warning。

### 25.5 Feature extraction nodes

新增节点：

#### ScriptFeatureExtractionNode

输入：

- ScriptVersion
- CreativeIntent

输出：

- partial CreativeFeatureVector

字段：

- hook_type
- script_structure
- topic_tags
- cta_type
- sentiment / angle

#### VideoFeatureExtractionNode

输入：

- VideoVersion
- TimelinePlan
- StylePlan
- FinishedVideo

输出：

- complete CreativeFeatureVector

字段：

- duration_sec
- broll_density
- cut_density
- subtitle_style_id
- bgm_id
- cover_style
- material_ids

### 25.6 PerformanceScore

```python
class PerformanceScore(BaseModel):
    observation_id: str
    case_id: str
    video_version_id: str
    window: Literal["24h", "3d", "7d", "30d"]
    primary_metric: Literal["completion_rate", "follow_rate", "conversion_rate", "engagement_rate"]
    normalized_score: float
    confidence: float
    sample_size: int
    excluded_reason: str | None = None
```

规则：

- impressions/views 低于阈值时不写高置信结论。
- 不同平台默认分开比较。
- 不同账号默认分开比较。
- 24h 只可作为早期信号，7d/30d 才可进入 active memory。

### 25.7 Memory 状态流

```text
proposed -> approved -> active
proposed -> rejected
active -> deprecated
active -> superseded
```

规则：

- approve 后进入 approved，不自动 active，除非 policy 允许。
- active 必须满足 sample_size 和 confidence 阈值，或人工强制激活。
- supersede 旧 memory 时，旧 memory 状态改 `superseded`。
- deprecated/superseded memory 不参与生成，只可作为历史展示。

### 25.8 CaseKnowledgeItem

```python
class CaseKnowledgeItem(BaseModel):
    id: str
    case_id: str
    kind: Literal["script", "video", "publish", "metric", "reflection", "memory"]
    ref_id: str
    summary: str
    tags: list[str]
    embedding_ref: str | None = None
    score: float | None = None
    created_at: datetime
```

`LoadCaseContextNode` 必须支持：

- 按 topic 检索。
- 按 platform 检索。
- 按 memory_type 检索。
- 最近 N 条。
- 高表现 N 条。
- 低表现 N 条。

### 25.9 generate-with-memory API

```python
class GenerateWithMemoryRequest(BaseModel):
    topic_hint: str | None = None
    target_platform: str | None = None
    count: int = Field(3, ge=1, le=20)
    use_memory_ids: list[str] = []
    avoid_memory_ids: list[str] = []

class GenerateWithMemoryResponse(BaseModel):
    strategy_artifact_id: str
    script_version_ids: list[str]
    used_memory_ids: list[str]
    avoided_memory_ids: list[str]
```

---

## 26. 阻塞点补齐附录 D：Ops 表、公式与治理 API

### 26.1 Ops 表最低字段

```python
class CostRollup(BaseModel):
    id: str
    window_start: datetime
    window_end: datetime
    group_by: Literal["case", "provider", "model", "prompt_version", "run", "job"]
    group_key: str
    estimated_cost: Money
    actual_cost: Money | None
    invocation_count: int
    updated_at: datetime

class Budget(BaseModel):
    id: str
    scope_type: Literal["global", "case", "provider", "capability", "team"]
    scope_id: str | None
    period: Literal["day", "week", "month"]
    limit: Money
    alert_threshold: float = 0.8
    enabled: bool = True

class OpsScopeFilter(BaseModel):
    case_ids: list[str] = []
    provider_ids: list[str] = []
    model_ids: list[str] = []
    capability_id: str | None = None
    prompt_template_ids: list[str] = []
    prompt_version_ids: list[str] = []
    environment: Literal["local", "dev", "staging", "prod"] | None = None

class OpsAlertRule(BaseModel):
    id: str
    metric: str
    condition: Literal["gt", "gte", "lt", "lte", "change_gt"]
    threshold: float
    scope: OpsScopeFilter
    channels: list[str]
    enabled: bool

class OpsAlertEvent(BaseModel):
    id: str
    rule_id: str
    status: Literal["open", "acknowledged", "resolved"]
    severity: Literal["info", "warning", "critical"]
    message: str
    triggered_at: datetime
    resolved_at: datetime | None = None

class ProductionQualityCheck(BaseModel):
    id: str
    target_type: Literal["run", "finished_video", "publish_package"]
    target_id: str
    check_type: Literal["auto", "manual", "platform_feedback"]
    result: Literal["passed", "failed", "warning", "manual_required"]
    reason_code: str | None
    reviewer: str | None
    evidence_artifact_id: str | None
    affects_true_yield: bool = True
    created_at: datetime

class YieldFunnelEvent(BaseModel):
    id: str
    job_id: str | None
    run_id: str | None
    finished_video_id: str | None
    publish_package_id: str | None
    publish_attempt_id: str | None
    event_type: str
    event_time: datetime
    dedupe_key: str

class AuditEvent(BaseModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    request_id: str
    ip: str | None
    created_at: datetime

class ApprovalRequest(BaseModel):
    id: str
    resource_type: str
    resource_id: str
    action: str
    status: Literal["pending", "approved", "rejected"]
    requested_by: str
    reviewed_by: str | None
    reason: str | None
    created_at: datetime
    reviewed_at: datetime | None
```

### 26.2 Cost 公式

```text
unit_cost_per_finished_video =
  sum(cost of provider_invocations in window) / count(finished_video_created events)

unit_cost_per_qc_passed_video =
  sum(cost) / count(qc_passed finished videos)

unit_cost_per_published_video =
  sum(cost) / count(published publish attempts deduped by publish_package_id)

wasted_cost =
  cost of runs whose final state failed
  + cost of finished videos with qc_failed/manual_rejected
  + cost of discarded finished videos

retry_cost =
  cost of runs where retry_of_run_id is not null
  + cost of nodes attempt > 1

cost_variance =
  actual_cost - estimated_cost
```

归因：

- retry/resume 成本同时归属新 run 和原 job。
- historical cost 不因新价格表自动重算，除非执行 explicit reconciliation。
- actual_cost 回填后修正 rollup。

### 26.3 Yield 公式

```text
technical_success_rate = succeeded runs / started runs
finished_video_rate = finished_video_created jobs / submitted jobs
qc_pass_rate = qc_passed finished videos / finished videos
approval_pass_rate = manual_approved / manual_review_started
publish_success_rate = published publish packages / publish_started publish packages
true_yield_rate = business_usable finished videos / submitted jobs
rework_rate = rework_required / finished videos
discard_rate = discarded / finished videos
```

去重：

- retry/resume 多个 run 归属于同一个 job。
- true_yield_rate 分母用 job。
- stage_pass_rate 分母用 node_started。

### 26.4 Prompt binding 解析

优先级从高到低：

1. exact case_id + node_id + provider_profile_id
2. case_id + node_id
3. node_id + provider_profile_id
4. node_id
5. capability + provider_profile_id
6. capability
7. template default published version

prod 环境同一优先级只允许一个 active binding。

### 26.5 Prompt Experiment

```python
class PromptExperimentScope(BaseModel):
    case_ids: list[str] = []
    node_ids: list[str] = []
    provider_profile_ids: list[str] = []
    capability_id: str | None = None
    environment: Literal["local", "dev", "staging", "prod"]

class PromptExperiment(BaseModel):
    id: str
    prompt_template_id: str
    status: Literal["draft", "running", "stopped", "completed"]
    variants: list[str]  # prompt_version_ids
    traffic_split: dict[str, float]
    scope: PromptExperimentScope
    start_at: datetime | None
    end_at: datetime | None

class PromptExperimentAssignment(BaseModel):
    id: str
    experiment_id: str
    subject_type: Literal["case", "job", "run"]
    subject_id: str
    prompt_version_id: str
    assigned_at: datetime
```

### 26.6 治理 API 补齐

- `GET/POST/PATCH /api/ops/budgets`
- `POST /api/ops/alerts/{event_id}/ack`
- `POST /api/ops/alerts/{event_id}/resolve`
- `POST /api/runs/{run_id}/quality-checks`
- `POST /api/finished-videos/{id}/quality-checks`
- `GET/POST/PATCH /api/prompts/bindings`
- `GET/POST/PATCH /api/prompts/experiments`
- `POST /api/approval-requests/{id}/approve`
- `POST /api/approval-requests/{id}/reject`
- `GET /api/providers/usage`
- `GET /api/providers/balances`
- `POST /api/providers/reconcile-billing`

---

## 27. 阻塞点补齐附录 E：Warning / Degradation / Provider 状态

### 27.1 WarningCode / DegradationCode

```python
class WarningCode(str, Enum):
    broll_skipped_no_material = "broll.skipped_no_material"
    bgm_skipped_library_unannotated = "bgm.skipped_library_unannotated"
    font_default_used = "font.default_used"
    cover_frame_fallback = "cover.frame_fallback"
    timestamp_estimated = "timestamp.estimated"
    cost_unpriced = "cost.unpriced"

class DegradationNotice(BaseModel):
    code: WarningCode
    message: str
    node_id: str | None
    affects_true_yield: bool = False
    details: dict[str, Any] = {}
```

### 27.2 Provider 状态流转

```text
prepared -> submitted -> polling -> succeeded
prepared|submitted|polling -> failed
submitted|polling -> timed_out
submitted|polling -> cancelled
```

规则：

- timed_out 是终态。
- 如果 provider 后续返回成功，但 invocation 已 timed_out/cancelled，不得自动变成 succeeded；只能记录 late_result。
- poll 必须幂等。
- submit 必须带 idempotency key。

### 27.3 Run cancelling 状态修正

RunStatus 增加：

```python
cancelling = "cancelling"
```

流转：

```text
running -> cancelling -> cancelled
```

---

## 28. 阻塞点补齐附录 F：Publishing 详细契约

### 28.1 PublishBatch / Item

```python
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

class PublishBatch(BaseModel):
    id: str
    case_id: str | None
    status: PublishBatchStatus
    defaults: PublishDefaults
    item_ids: list[str]
    created_at: datetime
    updated_at: datetime

class PublishBatchItem(BaseModel):
    id: str
    batch_id: str
    publish_package_id: str
    status: PublishItemStatus
    selected: bool = True
    asr_text: str = ""
    asr_segments_artifact_id: str | None = None
    generated_title: str = ""
    generated_description: str = ""
    cover_artifact_id: str | None = None
    overrides: dict[str, Any] = {}
    last_error: NodeError | None = None
```

### 28.2 PublishAttempt

```python
class PublishAttempt(BaseModel):
    id: str
    batch_id: str
    item_id: str
    platforms: list[str]
    manual_review: bool
    status: Literal["created", "manual_review_ready", "scheduled", "published", "failed"]
    adapter_id: str
    external_task_id: str | None
    results: list[dict[str, Any]]
    error: NodeError | None
    created_at: datetime
    finished_at: datetime | None
```

### 28.3 发布 API 补齐

- `POST /api/publish/batches/{batch_id}/items/{item_id}/generate-copy`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/generate-cover`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/preview-cover-frame`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/approve`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/exclude`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/retry-generation`
- `POST /api/publish/batches/{batch_id}/items/{item_id}/retry-publish`
- `GET /api/publish/platform-accounts`

---

## 29. 附录 G：从零导入协议

v3 只做面向新系统标准实体的 fresh import。旧仓库的具体文件路径、SQLite 表、JSON 字段不再是施工图的一部分。

### 29.1 Case 导入

```python
class CaseImportRow(BaseModel):
    external_id: str | None = None
    name: str
    description: str | None = None
    industry: str | None = None
    product: str | None = None
    target_audience: str | None = None
    owner_email: str | None = None
```

### 29.2 Script 导入

```python
class ScriptImportRow(BaseModel):
    case_external_id: str | None = None
    case_id: str | None = None
    title: str | None = None
    content: str
    publish_content: str | None = None
    source: Literal["manual", "agent", "imported"] = "imported"
    created_at: datetime | None = None
```

### 29.3 Media 导入

媒体导入必须走 UploadSession。批量导入工具只是 Upload API 的批处理客户端。

```python
class MediaImportManifestRow(BaseModel):
    case_id: str | None
    kind: UploadKind
    file_path: str
    title: str
    sha256: str | None = None
    metadata: dict[str, str] = {}
```

### 29.4 FinishedVideo / VideoVersion / PublishRecord 导入

历史成片导入不是旧结构兼容导入。它只接收成品文件和新 schema metadata，并在新系统里创建新实体。

```python
class FinishedVideoImportRow(BaseModel):
    external_id: str | None = None
    case_id: str | None = None
    case_external_id: str | None = None
    script_version_id: str | None = None
    script_external_id: str | None = None
    title: str
    video_file_path: str
    video_sha256: str | None = None
    cover_file_path: str | None = None
    subtitle_file_path: str | None = None
    duration_sec: float | None = None
    qc_status: Literal["pending", "passed", "failed", "manual_required"] = "manual_required"
    created_at: datetime | None = None

class VideoVersionImportRow(BaseModel):
    external_id: str | None = None
    case_id: str | None = None
    case_external_id: str | None = None
    finished_video_id: str | None = None
    finished_video_external_id: str | None = None
    script_version_id: str | None = None
    script_external_id: str | None = None
    created_at: datetime | None = None

class PublishRecordImportRow(BaseModel):
    external_id: str | None = None
    case_id: str | None = None
    case_external_id: str | None = None
    video_version_id: str | None = None
    video_version_external_id: str | None = None
    platform: str
    account_id: str | None = None
    title: str
    description: str = ""
    external_post_id: str | None = None
    external_url: str | None = None
    platform_item_id: str | None = None
    published_url: str | None = None
    published_at: datetime | None = None
    status: Literal["draft", "published", "failed", "deleted", "unknown"] = "unknown"
```

导入规则：

- FinishedVideo import 必须通过 UploadSession 创建 `video.finished` Artifact；cover/subtitle 也必须创建 Artifact 或留空。
- 导入的 FinishedVideo 必须创建 `Job(source=import)` 与 `WorkflowRun(workflow_template_id=import.finished_video, status=succeeded)`，满足 lineage，不伪造生产节点。
- VideoVersion import 若缺少 timeline/style plan，ImportService 必须创建最小 `plan.timeline` / `plan.style` artifact，标记 `source=imported_unavailable` 和 warning。
- PublishRecord import 必须绑定 VideoVersion，允许通过同批 `video_version_external_id` 解析。
- import report 必须输出 external_id 到新系统 id 的映射。

### 29.5 Performance 导入

```python
class PerformanceImportRow(BaseModel):
    case_id: str
    video_version_id: str | None = None
    video_version_external_id: str | None = None
    publish_record_id: str | None = None
    publish_record_external_id: str | None = None
    platform: str
    account_id: str | None = None
    observed_at: datetime
    window: Literal["1h", "24h", "3d", "7d", "30d"]
    impressions: int | None = None
    views: int | None = None
    completion_rate: float | None = None
    like_rate: float | None = None
    comment_rate: float | None = None
    share_rate: float | None = None
    follow_rate: float | None = None
    conversion_count: int | None = None
```

规则：

- `video_version_id` 或 `video_version_external_id` 必须二选一。
- `publish_record_id` 或 `publish_record_external_id` 必须二选一。
- external id 只能解析同一 import batch 或已登记的 import mapping。
- 解析失败、case 不匹配、platform 不匹配时整行拒绝。

### 29.6 Prompt Seed 导入

```python
class PromptSeedRow(BaseModel):
    template_name: str
    purpose: str
    content: str
    variables_schema_ref: PromptSchemaRef
    output_schema_ref: PromptSchemaRef
    initial_status: Literal["draft", "published"] = "draft"
```

### 29.7 导入工具要求

- 导入工具只接受新 schema。
- 导入结果必须输出 report：created / skipped / failed。
- 导入失败不得写半条业务记录。
- 素材导入后必须重新标注。
- 没有绑定 lineage 的 performance row 必须拒绝。
- FinishedVideo / VideoVersion / PublishRecord / PerformanceObservation 的 import 顺序必须固定为：FinishedVideo -> VideoVersion -> PublishRecord -> PerformanceObservation。
---

## 30. 阻塞点补齐附录 H：保真 API 与前端 ViewModel 补齐

### 30.1 Voice API

- `GET /api/voices`
- `POST /api/voices/clone`
- `POST /api/voices/design`
- `POST /api/voices/{voice_id}/preview`
- `PATCH /api/voices/{voice_id}`
- `DELETE /api/voices/{voice_id}`

### 30.2 Case Agent API

- `GET /api/cases/{case_id}/agent/source-bindings`
- `POST /api/cases/{case_id}/agent/source-bindings`
- `POST /api/cases/{case_id}/agent/import-source`
- `POST /api/cases/{case_id}/agent/runs`
- `GET /api/cases/{case_id}/agent/runs`
- `GET /api/cases/{case_id}/agent/runs/{run_id}`
- `GET /api/cases/{case_id}/agent/drafts`
- `POST /api/cases/{case_id}/agent/drafts/{draft_id}/adopt`
- `GET /api/cases/{case_id}/agent/memory-proposals`

Case Agent 输出契约：

- `CreativeBrief`
- `ScriptDraft`
- `CreativeIntentCandidate`
- `MemoryProposal`

不得直接创建 production node input。

### 30.3 FinishedVideo API

- `GET /api/cases/{case_id}/finished-videos`
- `GET /api/finished-videos/{id}`
- `GET /api/finished-videos/{id}/preview-url`
- `GET /api/finished-videos/{id}/download`
- `DELETE /api/finished-videos/{id}`
- `POST /api/finished-videos/{id}/editor-handoff`
- `POST /api/finished-videos/{id}/jianying-draft`

### 30.4 素材库 ViewModel

```ts
type MediaAssetCard = {
  assetId: string
  caseId?: string
  kind: "portrait" | "broll" | "voice" | "bgm" | "font" | "cover_template"
  title: string
  previewUrl?: string
  durationSec?: number
  annotationStatus?: string
  qualityStatus?: string
  usageLevel?: string
  warnings: string[]
}
```

### 30.5 Annotation Editor ViewModel

```ts
type AnnotationEditorVm = {
  assetId: string
  annotationId: string
  etag: string
  videoUrl: string
  timelineRows: AnnotationTimelineRow[]
  qualityEvents: QualityEventRow[]
  fieldMetadata: Record<string, FieldUiMetadata>
  canSave: boolean
}
```

### 30.6 Publish Center ViewModel

```ts
type PublishBatchVm = {
  batchId: string
  status: string
  items: PublishBatchItemVm[]
  defaults: PublishDefaults
  readyCount: number
  failedCount: number
  publishedCount: number
}

type PublishBatchItemVm = {
  itemId: string
  status: string
  selected: boolean
  videoPreviewUrl: string
  coverUrl?: string
  title: string
  description: string
  platforms: string[]
  warnings: string[]
  canApprove: boolean
  canPublish: boolean
  canRetryGeneration: boolean
  canRetryPublish: boolean
}
```

### 30.7 Ops ViewModel

```ts
type OpsOverviewVm = {
  todayCost: MoneyVm
  finishedVideos: number
  trueYieldRate: number
  providerFailureRate: number
  openAlerts: number
  topFailureReasons: Array<{ code: string; count: number }>
}
```

---

## 31. 三审前自检清单

实施 Agent 或 reviewer 应逐项确认：

- [ ] 所有引用类型都有最低字段定义。
- [ ] 所有 artifact kind 都能找到 payload schema。
- [ ] 所有节点输入输出都有 schema。
- [ ] Case lineage 从 script 到 metrics 能串起来。
- [ ] 成本公式有 numerator/denominator。
- [ ] 成品率公式有去重规则。
- [ ] Prompt binding 有优先级。
- [ ] Provider 状态迁移有定义。
- [ ] Publishing item/attempt/review 契约完整。
- [ ] Fresh import 有 schema、校验、报告和幂等规则。
- [ ] 保真矩阵里的每个用户流程都有 API 或 ViewModel 承接。

---

## 32. 最终契约收口附录：覆盖所有剩余冲突

本章是对前文的补丁和覆盖。若本章与前文冲突，以本章为准。

### 32.1 ArtifactKind 最终全集

`ArtifactKind` 必须至少包含：

```python
class ArtifactKind(str, Enum):
    validated_production_spec = "spec.validated_production"
    case_context = "case.context"
    case_performance_analysis = "case.performance_analysis"
    case_reflection = "case.reflection"
    script_strategy = "script.strategy"

    creative_intent = "creative.intent"
    audio_tts = "audio.tts"
    audio_alignment_raw = "audio.alignment.raw"
    audio_alignment = "audio.alignment"
    narration_units = "narration.units"

    material_pack = "plan.material_pack"
    portrait_plan = "plan.portrait"
    broll_plan = "plan.broll"
    style_plan = "plan.style"
    timeline_plan = "plan.timeline"
    render_plan = "plan.render"

    video_portrait_track = "video.portrait_track"
    video_lipsync = "video.lipsync"
    lipsync_report = "lipsync.report"
    video_rendered = "video.rendered"
    video_final = "video.final"
    video_finished = "video.finished"

    subtitle_ass = "subtitle.ass"
    cover_image = "cover.image"
    editor_handoff_package = "editor.handoff_package"
    jianying_draft_package = "editor.jianying_draft_package"
    publish_package = "publish.package"

    run_public_report = "run.report.public"
    run_debug_report = "run.report.debug"
    provider_raw_request = "provider.raw_request"
    provider_raw_response = "provider.raw_response"
```

规则：

- 媒体二进制 artifact 可以 `payload=None`，但必须有 `MediaInfo`。
- JSON artifact 必须有 payload schema。
- package artifact 必须有 package manifest schema。

### 32.2 Artifact schema 映射表

| ArtifactKind | Schema |
|---|---|
| `spec.validated_production` | `ValidatedProductionSpecArtifact` |
| `case.context` | `CaseContextArtifact` |
| `case.performance_analysis` | `PerformanceAnalysisArtifact` |
| `case.reflection` | `ReflectionReportArtifact` |
| `script.strategy` | `ScriptStrategyArtifact` |
| `creative.intent` | `CreativeIntentArtifact` |
| `audio.alignment.raw` | `RawAlignmentArtifact` |
| `audio.alignment` | `AlignmentArtifact` |
| `narration.units` | `NarrationUnitsArtifact` |
| `plan.material_pack` | `MaterialPackArtifact` |
| `plan.portrait` | `PortraitPlanArtifact` |
| `plan.broll` | `BrollPlanArtifact` |
| `plan.style` | `StylePlanArtifact` |
| `plan.timeline` | `TimelinePlanArtifact` |
| `plan.render` | `RenderPlanArtifact` |
| `lipsync.report` | `LipSyncReportArtifact` |
| `editor.handoff_package` | `EditorHandoffPackageArtifact` |
| `editor.jianying_draft_package` | `JianyingDraftPackageArtifact` |
| `publish.package` | `PublishPackageArtifact` |
| `run.report.public` | `RunPublicReportArtifact` |
| `run.report.debug` | `RunDebugReportArtifact` |
| `provider.raw_request` | `ProviderRawRequestArtifact` |
| `provider.raw_response` | `ProviderRawResponseArtifact` |

URI-only artifact kinds:

| ArtifactKind | Required metadata |
|---|---|
| `audio.tts` | `MediaInfo` + sha256 |
| `video.portrait_track` | `MediaInfo` + sha256 |
| `video.lipsync` | `MediaInfo` + sha256 |
| `video.rendered` | `MediaInfo` + sha256 |
| `video.final` | `MediaInfo` + sha256 |
| `video.finished` | `MediaInfo` + sha256 |
| `subtitle.ass` | `MediaInfo` + sha256 |
| `cover.image` | `MediaInfo` + sha256 |

```python
class ValidatedProductionSpecArtifact(BaseModel):
    request_id: str
    case_id: str
    workflow_template_id: str
    workflow_template_version: str
    validation_errors: list[NodeError] = []
    validation_warnings: list[DegradationNotice] = []
    normalized_request_artifact_id: str | None = None

class RawAlignmentArtifact(BaseModel):
    provider_invocation_id: str | None
    format: Literal["json", "srt", "textgrid", "provider_raw"]
    source_artifact_id: str | None
    segments: list[dict[str, JsonValue]] = []

class AlignmentSegment(BaseModel):
    text: str
    start_sec: float
    end_sec: float
    word_confidence: float | None = None

class AlignmentArtifact(BaseModel):
    audio_artifact_id: str
    segments: list[AlignmentSegment]
    language: str | None = None

class PublishPackageArtifact(BaseModel):
    publish_package_id: str
    manifest_version: str
    video_artifact_id: str
    cover_artifact_id: str | None = None
    title: str
    description: str
    platform_targets: list[str] = []

class ProviderRawRequestArtifact(BaseModel):
    provider_invocation_id: str
    redaction_policy_version: str
    body_artifact_uri: str
    content_type: str

class ProviderRawResponseArtifact(BaseModel):
    provider_invocation_id: str
    redaction_policy_version: str
    body_artifact_uri: str
    content_type: str
    status_code: int | None = None
```

### 32.3 Case 自进化缺失 Schema

```python
class PerformanceMetricView(BaseModel):
    case_id: str
    window: Literal["24h", "3d", "7d", "30d"]
    video_count: int
    median_views: float | None = None
    median_completion_rate: float | None = None
    median_engagement_rate: float | None = None
    top_video_version_ids: list[str] = []
    low_video_version_ids: list[str] = []

class PerformanceAnalysisArtifact(BaseModel):
    case_id: str
    observation_ids: list[str]
    feature_vector_ids: list[str]
    scores: list[PerformanceScore]
    top_patterns: list["CreativePattern"]
    weak_patterns: list["CreativePattern"]
    caveats: list[str]
    generated_at: datetime

class CreativePattern(BaseModel):
    pattern_id: str
    pattern_type: Literal["hook", "script_structure", "editing", "cover", "title", "material", "cta"]
    statement: str
    evidence_refs: list[str]
    confidence: float
    sample_size: int

class MemoryProposal(BaseModel):
    id: str
    case_id: str
    memory_type: Literal["script_pattern", "video_pattern", "audience_insight", "editing_rule", "negative_lesson"]
    statement: str
    evidence_refs: list[str]
    confidence: float
    sample_size: int
    scope: CaseMemoryScope
    proposed_by_reflection_run_id: str
    status: Literal["proposed", "approved", "rejected", "committed"] = "proposed"
    target_case_memory_id: str | None = None

class ReflectionReportArtifact(BaseModel):
    case_id: str
    performance_analysis_artifact_id: str
    summary: str
    findings: list[CreativePattern]
    memory_proposals: list[MemoryProposal]
    caveats: list[str]
    generated_at: datetime

class ScriptStrategyArtifact(BaseModel):
    case_id: str
    goal: str
    used_memory_ids: list[str]
    avoided_memory_ids: list[str]
    strategy_points: list[str]
    constraints: list[str]
    prompt_guidance: str
```

MemoryProposal 与 CaseMemory 的关系：

- Reflection 先创建 `MemoryProposal`。
- 审核通过后，`MemoryProposal.status=committed`，并创建或更新 `CaseMemory`。
- `ReflectionRun.memory_proposal_ids` 指向 `MemoryProposal` 表。
- `CaseMemory.status` 最终枚举必须包含：

```python
Literal["proposed", "approved", "active", "deprecated", "rejected", "superseded"]
```

### 32.4 Case Agent 输出 Schema

```python
class CaseAgentSourceBinding(BaseModel):
    id: str
    case_id: str
    source_type: Literal["url", "text", "file", "manual_note"]
    source_ref: str
    title: str | None = None
    status: Literal["active", "disabled", "failed"] = "active"
    created_by: str
    created_at: datetime
    updated_at: datetime | None = None

class CaseAgentRun(BaseModel):
    id: str
    case_id: str
    goal: Literal["brief", "script_draft", "memory_proposal"]
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    source_binding_ids: list[str] = []
    provider_invocation_ids: list[str] = []
    output_brief_ids: list[str] = []
    output_script_draft_ids: list[str] = []
    output_memory_proposal_ids: list[str] = []
    error: NodeError | None = None
    created_by: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

class CreativeBrief(BaseModel):
    id: str
    case_id: str
    topic: str
    audience: str | None
    key_insights: list[str]
    source_refs: list[str]
    generated_by_run_id: str

class ScriptDraft(BaseModel):
    id: str
    case_id: str
    brief_id: str | None
    title: str
    content: str
    publish_content: str | None = None
    used_memory_ids: list[str] = []
    confidence: float | None = None
    status: Literal["draft", "adopted", "rejected"] = "draft"
    generated_by_run_id: str

class CreativeIntentCandidate(BaseModel):
    id: str
    case_id: str
    script_draft_id: str
    creative_intent: CreativeIntentArtifact
    rationale: str
```

采用草稿规则：

- `POST /agent/drafts/{draft_id}/adopt` 必须创建 `ScriptVersion(source=agent)`。
- ScriptVersion 必须记录 `source_draft_id`。
- Production Job 必须使用该 `script_version_id`。

### 32.5 Annotation Editor 类型

```python
class AnnotationTimelineRow(BaseModel):
    row_id: str
    segment_id: str
    start: float
    end: float
    summary: str
    role: str
    shot_scale: str | None = None
    scene_type: str | None = None
    confidence: float | None = None
    editable_fields: dict[str, Any] = {}

class QualityEventRow(BaseModel):
    event_id: str
    event_type: str
    start: float
    end: float
    description: str
    severity: int
    source: Literal["sensor", "vlm", "manual"]

class FieldUiMetadata(BaseModel):
    field: str
    label: str
    input_type: Literal["text", "number", "select", "multi_select", "boolean"]
    options: list[str] = []
    required: bool = False
    read_only: bool = False
```

### 32.6 业务关键 dict 的强类型替换

以下字段不得用 `dict[str, Any]`：

```python
class MaterialCandidate(BaseModel):
    candidate_id: str
    asset_id: str
    material_type: Literal["portrait", "broll", "font", "bgm"]
    annotation_id: str | None = None
    score: float
    reason: str
    diversity_key: str | None = None
    risk_flags: list[str] = []

class SubtitleStylePlan(BaseModel):
    enabled: bool
    style_preset: str
    font_id: str | None
    font_size: int | None
    position: dict[str, float] | None

class BgmPlan(BaseModel):
    enabled: bool
    bgm_id: str | None
    volume: float
    auto_mix: bool
    skipped_reason: str | None = None

class FontPlan(BaseModel):
    font_id: str | None
    source: Literal["manual", "agent", "default"]
    skipped_reason: str | None = None

class TimelineValidationReport(BaseModel):
    valid: bool
    errors: list[NodeError] = []
    warnings: list[DegradationNotice] = []

class CostSummary(BaseModel):
    estimated_total: Money | None
    actual_total: Money | None
    unpriced_invocation_count: int = 0
    by_provider: dict[str, Money] = {}

class NodeSummary(BaseModel):
    node_id: str
    status: NodeStatus
    message: str
    warnings: list[DegradationNotice] = []
```

覆盖前文：

- `MaterialPackArtifact.*_candidate` 必须用 `list[MaterialCandidate]`。
- `StylePlanArtifact.subtitle` 必须用 `SubtitleStylePlan`。
- `StylePlanArtifact.bgm` 必须用 `BgmPlan | None`。
- `StylePlanArtifact.font` 必须用 `FontPlan | None`。
- `TimelinePlanArtifact.validation` 必须用 `TimelineValidationReport`。
- `RunPublicReportArtifact.cost_summary` 必须用 `CostSummary`。
- `RunPublicReportArtifact.node_summaries` 必须用 `list[NodeSummary]`。

### 32.7 Prompt SchemaRef

```python
class PromptSchemaRef(BaseModel):
    schema_id: str
    schema_version: str
    dialect: Literal["json_schema_2020_12", "pydantic"]
    schema_artifact_id: str | None = None

class PromptVersion(BaseModel):
    ...
    variables_schema_ref: PromptSchemaRef
    output_schema_ref: PromptSchemaRef
    output_validation_failure_policy: Literal["retry", "hard_fail"] = "retry"
```

废弃前文 `variables_schema: dict[str, Any]` 和 `output_schema: dict[str, Any]`。

### 32.8 Ops 剩余表 Schema

```python
class ProviderPriceCatalog(BaseModel):
    id: str
    name: str
    environment: Literal["dev", "staging", "prod"]
    status: Literal["draft", "reviewing", "approved", "published", "deprecated"]
    currency_policy: Literal["native", "convert_to_cny", "convert_to_usd"]
    effective_from: datetime
    effective_to: datetime | None
    created_by: str
    approved_by: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

class ExchangeRate(BaseModel):
    id: str
    source_currency: str
    target_currency: str
    rate: Decimal
    source: str
    effective_from: datetime
    effective_to: datetime | None
    created_at: datetime

class FailureTaxonomy(BaseModel):
    code: str
    category: str
    label: str
    severity: Literal["info", "warning", "error", "critical"]
    retryable_default: bool
    affects_true_yield_default: bool
    owner_domain: str
    created_at: datetime
```

Yield 事件补充：

- `manual_review_started`
- `business_usable_marked`
- `rework_required`
- `discarded`

这些事件由 QualityGateService 或人工审核接口写入，绑定层级：

- `manual_review_started`：finished_video 或 publish_package。
- `business_usable_marked`：finished_video。
- `rework_required`：finished_video。
- `discarded`：finished_video。

### 32.9 审计硬规则

`audit_events` 必须 append-only：

- 不允许 update。
- 不允许 delete。
- 审计写失败时，以下关键治理操作必须失败。

必须审计动作：

- price_catalog.create / approve / publish / deprecate
- prompt.create / approve / publish / rollback
- prompt_binding.create / update / delete
- prompt_experiment.start / stop
- provider_profile.create / update / disable
- secret.read
- budget.create / update / delete
- alert_rule.create / update / delete
- quality_check.manual_review
- publish.approve / publish.start / publish.retry
- permission.change
- billing.reconcile

### 32.10 主业务表最低字段

```python
class UserRecord(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal["admin", "operator", "viewer"]
    status: Literal["active", "disabled"]

class CaseRecord(BaseModel):
    id: str
    name: str
    description: str | None
    industry: str | None
    product: str | None
    target_audience: str | None
    owner_user_id: str
    status: Literal["active", "archived"]

class MediaAssetRecord(BaseModel):
    id: str
    case_id: str | None
    kind: Literal["portrait", "broll", "voice", "bgm", "font", "cover_template"]
    title: str
    source_artifact_id: str
    thumbnail_artifact_id: str | None
    annotation_id: str | None
    status: Literal["ready", "processing", "failed", "archived"]

class AnnotationRecord(BaseModel):
    id: str
    asset_id: str
    schema_version: str
    canonical_artifact_id: str
    status: Literal["pending", "completed", "failed"]
    etag: str

class AnnotationProjectionRecord(BaseModel):
    id: str
    annotation_id: str
    projection_type: Literal["ui", "search", "material_planning", "reporting"]
    projection_artifact_id: str
    schema_version: str

class SelectionLedgerRecord(BaseModel):
    id: str
    case_id: str
    run_id: str
    medium: Literal["portrait", "broll", "bgm", "font"]
    item_id: str
    diversity_key: str | None
    committed_at: datetime

class SelectionReservationRecord(BaseModel):
    id: str
    case_id: str
    run_id: str
    medium: str
    item_id: str
    expires_at: datetime
    status: Literal["reserved", "committed", "released", "expired"]
```

### 32.11 核心 API Request / Response 契约

```python
class CreateDigitalHumanVideoJobResponse(BaseModel):
    job: Job
    initial_run: WorkflowRun | None

class StartRunRequest(BaseModel):
    reason: str | None = None

class StartRunResponse(BaseModel):
    run: WorkflowRun

class RetryRunResponse(BaseModel):
    job_id: str
    retry_run: WorkflowRun

class ResumeRunResponse(BaseModel):
    job_id: str
    source_run_id: str
    resumed_run: WorkflowRun
    reused_artifact_ids: list[str]

class UploadMediaAssetRequest(BaseModel):
    case_id: str | None
    kind: str
    title: str
    source_upload_id: str

class UploadMediaAssetResponse(BaseModel):
    asset: MediaAssetRecord

class PatchAnnotationResponse(BaseModel):
    annotation: AnnotationRecord
    edit_view: AnnotationEditView

class ProviderCapabilitiesResponse(BaseModel):
    capabilities: list[ProviderCapability]
```

HTTP 语义：

- create job 成功：201。
- Idempotency-Key 命中：200，返回原 job/run。
- resume 成功：201，返回新 run。
- retry 成功：201，返回新 run。
- validation error：422 + error body。
- domain conflict：409 + error body。

### 32.12 Editor Handoff / Jianying Package

```python
class EditorHandoffPackageArtifact(BaseModel):
    finished_video_id: str
    package_uri: str
    manifest_path: str
    assets: list[ArtifactRef]
    warnings: list[str] = []

class JianyingDraftPackageArtifact(BaseModel):
    finished_video_id: str
    draft_uri: str
    draft_name: str
    draft_id: str | None
    tracks_summary: dict[str, Any]
    warnings: list[str] = []
```

生成节点：

- `ExportFinishedVideoNode` 可以产出 package artifact。
- 或单独 `EditorHandoffExportNode` 按需生成。

API：

- `POST /api/finished-videos/{id}/editor-handoff` 返回 `EditorHandoffPackageArtifact`。
- `POST /api/finished-videos/{id}/jianying-draft` 返回 `JianyingDraftPackageArtifact`。

### 32.13 最终自检更新

只有当以下全部成立，才算无阻塞：

- `ArtifactKind` 全集里的每个 kind 都有 schema 或 uri-only 规则。
- 所有节点输出 artifact 都在 ArtifactKind 全集。
- 所有保真矩阵能力都有 API 和 ViewModel。
- 所有核心 API 都有 request/response。
- 所有 prompt schema 都通过 PromptSchemaRef。
- 所有 Case memory 状态都能通过枚举校验。
- Ops 的价格、汇率、失败分类、yield 事件、审计动作都有最低契约。

---

## 33. 最终红队补齐：Auth 与 Upload 入口契约

本章补齐两个入口级能力：认证/会话和文件上传。它们是完整系统的地基，必须先于素材库、发布中心和生产任务实现。

### 33.1 Auth 数据模型

```python
class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal["admin", "operator", "viewer"]
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime

class SessionInfo(BaseModel):
    user: AuthUser
    session_id: str
    expires_at: datetime

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str
    registration_code: str | None = None

class AuthResponse(BaseModel):
    user: AuthUser
    session: SessionInfo

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class AdminCreateUserRequest(BaseModel):
    email: str
    display_name: str
    role: Literal["admin", "operator", "viewer"]
    password: str | None = None

class AdminUpdateUserRequest(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "operator", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None
```

### 33.2 Auth API

必须实现：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/session`
- `GET /api/auth/me`
- `PATCH /api/auth/me`
- `POST /api/auth/me/change-password`
- `GET /api/auth/users` admin only
- `POST /api/auth/users` admin only
- `PATCH /api/auth/users/{user_id}` admin only
- `GET /api/auth/registration-codes` admin only
- `POST /api/auth/registration-codes` admin only
- `PATCH /api/auth/registration-codes/{code_id}` admin only

认证规则：

- Web 默认使用 HttpOnly cookie session。
- API 也可支持 bearer token，但不能要求前端把 token 存 localStorage。
- 所有非 auth API 默认需要登录。
- admin API 必须校验 role。
- session cookie 必须 `HttpOnly`，生产环境必须 `Secure`。
- logout 必须让 session 失效。
- 修改 provider profile、prompt、价格、预算、审计敏感接口必须 admin。

错误码：

- `auth.unauthorized`
- `auth.forbidden`
- `auth.invalid_credentials`
- `auth.registration_closed`
- `auth.user_disabled`

### 33.3 上传会话模型

所有用户上传文件都先创建 UploadSession，再完成为 MediaAsset / PublishPackage / Artifact。

```python
class UploadKind(str, Enum):
    portrait = "portrait"
    broll = "broll"
    voice_reference = "voice_reference"
    bgm = "bgm"
    font = "font"
    cover_template = "cover_template"
    publish_video = "publish_video"

class UploadSessionStatus(str, Enum):
    prepared = "prepared"
    uploading = "uploading"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class PrepareUploadRequest(BaseModel):
    kind: UploadKind
    case_id: str | None = None
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None = None
    multipart: bool = False

class UploadSession(BaseModel):
    id: str
    kind: UploadKind
    case_id: str | None
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    status: UploadSessionStatus
    upload_url: str | None = None
    local_temp_path: str | None = None
    expires_at: datetime
    created_by: str
    created_at: datetime

class CompleteUploadRequest(BaseModel):
    upload_session_id: str
    sha256: str | None = None
    metadata: dict[str, str] = {}

class CompleteUploadResponse(BaseModel):
    upload_session: UploadSession
    artifact: ArtifactRef
    media_asset: MediaAssetRecord | None = None
    publish_package: PublishPackage | None = None
```

### 33.4 Upload API

必须实现：

- `POST /api/uploads/prepare`
- `PUT /api/uploads/{upload_session_id}/file` 普通 multipart 上传
- `POST /api/uploads/complete`
- `POST /api/uploads/{upload_session_id}/cancel`
- `GET /api/uploads/{upload_session_id}`

上传行为：

- 小文件可走 multipart 到 API。
- 大文件可返回 signed upload URL 或分片上传信息。
- complete 时必须校验 size。
- 如果 request 提供 sha256，complete 时必须校验 sha256。
- complete 成功后必须创建 Artifact。
- 对 `portrait/broll/bgm/font/cover_template/voice_reference`，complete 成功后创建 MediaAssetRecord。
- 对 `publish_video`，complete 成功后创建 PublishPackage 或返回 artifact 供发布批次使用。
- failed/cancelled upload session 不得被 complete。
- 过期未完成的 session 由 cleanup job 清理临时文件。

### 33.5 Upload 与业务流程绑定

| 上传 kind | complete 后创建 |
|---|---|
| `portrait` | MediaAsset(kind=portrait)，可触发 annotation |
| `broll` | MediaAsset(kind=broll)，可触发 annotation |
| `voice_reference` | Artifact，供 VoiceClone job 使用 |
| `bgm` | MediaAsset(kind=bgm)，可触发 BGM analysis |
| `font` | MediaAsset(kind=font)，可触发 Font analysis |
| `cover_template` | MediaAsset(kind=cover_template) |
| `publish_video` | PublishPackage 或 upload artifact |

保真矩阵里所有上传流程必须走本章契约，不允许页面各自手写上传逻辑。

---

## 34. 最终 API Contract Matrix

本章是唯一 API 实施矩阵，覆盖前文所有“只列路径”的 API。前文若仍出现冲突路径、旧 path name 或不同 method，以本章为准；实施 Agent 不得为了兼容前文旧路径额外实现重复 endpoint。

通用约定：

- `-` 表示无 body。
- 所有列表响应使用 `PageResponse[T]`，字段为 `items`、`next_cursor`、`total_hint`。
- 所有写接口必须支持 `Idempotency-Key`。
- 所有响应包含 `request_id`。
- admin 表示 `role=admin`；operator 表示 admin/operator；viewer 表示登录用户均可读。

### 34.1 Auth / Upload / Secrets

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/auth/register` | POST | `RegisterRequest` | `AuthResponse` | 201 | `auth.registration_closed` | public |
| `/api/auth/login` | POST | `LoginRequest` | `AuthResponse` | 200 | `auth.invalid_credentials`, `auth.user_disabled` | public |
| `/api/auth/logout` | POST | - | `OkResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/auth/session` | GET | - | `SessionInfo` | 200 | `auth.unauthorized` | viewer |
| `/api/auth/me` | GET | - | `AuthUser` | 200 | `auth.unauthorized` | viewer |
| `/api/auth/me` | PATCH | `UpdateMeRequest` | `AuthUser` | 200 | `validation.invalid_options` | viewer |
| `/api/auth/me/change-password` | POST | `ChangePasswordRequest` | `OkResponse` | 200 | `auth.invalid_credentials` | viewer |
| `/api/auth/users` | GET | `UserListQuery` | `PageResponse[AuthUser]` | 200 | `auth.forbidden` | admin |
| `/api/auth/users` | POST | `AdminCreateUserRequest` | `AuthUser` | 201 | `validation.invalid_options` | admin |
| `/api/auth/users/{user_id}` | PATCH | `AdminUpdateUserRequest` | `AuthUser` | 200 | `auth.forbidden` | admin |
| `/api/auth/registration-codes` | GET | `RegistrationCodeQuery` | `PageResponse[RegistrationCodePreview]` | 200 | `auth.forbidden` | admin |
| `/api/auth/registration-codes` | POST | `CreateRegistrationCodeRequest` | `RegistrationCodePreview` | 201 | `auth.forbidden` | admin |
| `/api/auth/registration-codes/{code_id}` | PATCH | `UpdateRegistrationCodeRequest` | `RegistrationCodePreview` | 200 | `auth.forbidden` | admin |
| `/api/uploads/prepare` | POST | `PrepareUploadRequest` | `UploadSession` | 201 | `upload.unsupported_type` | operator |
| `/api/uploads/{upload_session_id}/file` | PUT | binary | `UploadSession` | 200 | `upload.expired`, `upload.invalid_state` | operator |
| `/api/uploads/complete` | POST | `CompleteUploadRequest` | `CompleteUploadResponse` | 200 | `upload.size_mismatch`, `upload.sha256_mismatch`, `upload.invalid_state` | operator |
| `/api/uploads/{upload_session_id}/cancel` | POST | - | `UploadSession` | 200 | `upload.invalid_state` | operator |
| `/api/uploads/{upload_session_id}` | GET | - | `UploadSession` | 200 | `auth.unauthorized` | operator |
| `/api/secrets` | GET | `SecretQuery` | `PageResponse[SecretPreview]` | 200 | `auth.forbidden` | admin |
| `/api/secrets` | POST | `CreateSecretRequest` | `SecretPreview` | 201 | `validation.invalid_options` | admin |
| `/api/secrets/{secret_id}/rotate` | POST | `RotateSecretRequest` | `SecretPreview` | 200 | `auth.forbidden` | admin |
| `/api/secrets/{secret_id}/disable` | PATCH | `DisableSecretRequest` | `SecretPreview` | 200 | `auth.forbidden` | admin |

### 34.2 Cases / Jobs / Runs

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/cases` | GET | `CaseListQuery` | `PageResponse[CaseListItem]` | 200 | `auth.unauthorized` | viewer |
| `/api/cases` | POST | `CreateCaseRequest` | `CaseDetail` | 201 | `validation.invalid_options` | operator |
| `/api/cases/{case_id}` | GET | - | `CaseDetail` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}` | PATCH | `PatchCaseRequest` | `CaseDetail` | 200 | `validation.missing_case` | operator |
| `/api/jobs/digital-human-video` | POST | `CreateDigitalHumanVideoJobRequest` | `CreateJobResponse` | 201 | `validation.missing_case`, `validation.missing_voice`, `prompt.version_not_published` | operator |
| `/api/jobs/{job_id}` | GET | - | `JobDetailResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/jobs/{job_id}/runs` | POST | `CreateRunRequest` | `WorkflowRunResponse` | 201 | `workflow.invalid_transition` | operator |
| `/api/runs/{run_id}` | GET | - | `RunDetailResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/runs/{run_id}/cancel` | POST | `CancelRunRequest` | `RunActionResponse` | 202 | `workflow.invalid_transition` | operator |
| `/api/runs/{run_id}/retry` | POST | `RetryRunRequest` | `RetryRunResponse` | 201 | `workflow.resume_not_allowed` | operator |
| `/api/runs/{run_id}/resume` | POST | `ResumeRunRequest` | `ResumeRunResponse` | 201 | `workflow.resume_not_allowed`, `artifact.missing` | operator |
| `/api/runs/{run_id}/report` | GET | - | `RunReportResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/runs/{run_id}/artifacts` | GET | - | `RunArtifactsResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/runs/{run_id}/events` | GET | `RunEventsQuery` | `EventStreamTokenResponse` | 200 | `auth.unauthorized` | viewer |

### 34.3 Media / Annotation / Voice

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/media/assets` | GET | `MediaAssetQuery` | `PageResponse[MediaAssetCard]` | 200 | `auth.unauthorized` | viewer |
| `/api/media/assets` | POST | `CreateMediaAssetFromUploadRequest` | `MediaAssetRecord` | 201 | `upload.invalid_state` | operator |
| `/api/media/assets/{asset_id}` | GET | - | `MediaAssetDetail` | 200 | `artifact.missing` | viewer |
| `/api/media/assets/{asset_id}/preview-url` | GET | - | `SignedUrlResponse` | 200 | `artifact.missing` | viewer |
| `/api/annotations/{asset_id}` | GET | - | `AnnotationEditorVm` | 200 | `material.annotation_failed` | viewer |
| `/api/annotations/{asset_id}` | PATCH | `PatchAnnotationRequest` | `AnnotationEditorVm` | 200 | `artifact.schema_mismatch` | operator |
| `/api/annotations/{asset_id}/rerun` | POST | `RerunAnnotationRequest` | `AnnotationRunResponse` | 202 | `provider.quota_exceeded` | operator |
| `/api/voices` | GET | `VoiceQuery` | `PageResponse[VoiceProfile]` | 200 | `auth.unauthorized` | viewer |
| `/api/voices/clone` | POST | `CloneVoiceRequest` | `VoiceProfile` | 202 | `provider.quota_exceeded`, `provider.timeout` | operator |
| `/api/voices/design` | POST | `DesignVoiceRequest` | `VoiceProfile` | 202 | `provider.remote_failed` | operator |
| `/api/voices/{voice_id}/preview` | POST | `VoicePreviewRequest` | `VoicePreviewResponse` | 200 | `provider.timeout` | operator |
| `/api/voices/{voice_id}` | PATCH | `PatchVoiceRequest` | `VoiceProfile` | 200 | `validation.invalid_options` | operator |
| `/api/voices/{voice_id}` | DELETE | - | `OkResponse` | 200 | `workflow.invalid_transition` | admin |

### 34.4 Prompt / Provider / Price

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/prompts` | GET | `PromptTemplateQuery` | `PageResponse[PromptTemplateView]` | 200 | `auth.unauthorized` | viewer |
| `/api/prompts` | POST | `CreatePromptTemplateRequest` | `PromptTemplateView` | 201 | `validation.invalid_options` | admin |
| `/api/prompts/{template_id}/versions` | GET | `BaseListQuery` | `PageResponse[PromptVersionView]` | 200 | `auth.unauthorized` | viewer |
| `/api/prompts/{template_id}/versions` | POST | `CreatePromptVersionRequest` | `PromptVersionView` | 201 | `prompt.output_invalid` | admin |
| `/api/prompts/{template_id}/versions/{version_id}/approve` | POST | `ApprovePromptVersionRequest` | `PromptVersionView` | 200 | `auth.forbidden` | admin |
| `/api/prompts/{template_id}/versions/{version_id}/publish` | POST | `PublishPromptVersionRequest` | `PromptVersionView` | 200 | `prompt.output_invalid` | admin |
| `/api/prompts/{template_id}/rollback` | POST | `RollbackPromptRequest` | `PromptVersionView` | 200 | `prompt.version_not_published` | admin |
| `/api/prompts/bindings` | GET | `PromptBindingQuery` | `PageResponse[PromptBindingView]` | 200 | `auth.unauthorized` | viewer |
| `/api/prompts/bindings` | POST | `CreatePromptBindingRequest` | `PromptBindingView` | 201 | `validation.invalid_options` | admin |
| `/api/prompts/bindings/{binding_id}` | PATCH | `PatchPromptBindingRequest` | `PromptBindingView` | 200 | `validation.invalid_options` | admin |
| `/api/prompts/experiments` | GET | `PromptExperimentQuery` | `PageResponse[PromptExperiment]` | 200 | `auth.unauthorized` | viewer |
| `/api/prompts/experiments` | POST | `CreatePromptExperimentRequest` | `PromptExperiment` | 201 | `validation.invalid_options` | admin |
| `/api/prompts/experiments/{experiment_id}` | PATCH | `PatchPromptExperimentRequest` | `PromptExperiment` | 200 | `validation.invalid_options` | admin |
| `/api/providers/profiles` | GET | `ProviderProfileQuery` | `PageResponse[ProviderProfile]` | 200 | `auth.unauthorized` | viewer |
| `/api/providers/profiles` | POST | `CreateProviderProfileRequest` | `ProviderProfile` | 201 | `provider.auth_failed`, `validation.invalid_options` | admin |
| `/api/providers/profiles/{profile_id}` | PATCH | `PatchProviderProfileRequest` | `ProviderProfile` | 200 | `provider.unsupported_option` | admin |
| `/api/providers/profiles/{profile_id}/test` | POST | `TestProviderProfileRequest` | `ProviderHealthCheckResponse` | 200 | `provider.auth_failed`, `provider.timeout` | admin |
| `/api/providers/capabilities` | GET | - | `list[ProviderCapability]` | 200 | `auth.unauthorized` | viewer |
| `/api/providers/price-catalogs` | GET | `PriceCatalogQuery` | `PageResponse[ProviderPriceCatalog]` | 200 | `auth.unauthorized` | viewer |
| `/api/providers/price-catalogs` | POST | `UpsertPriceCatalogRequest` | `ProviderPriceCatalog` | 201 | `validation.invalid_options` | admin |
| `/api/providers/price-catalogs/{catalog_id}/approve` | POST | `GovernedActionRequest` | `ProviderPriceCatalog` | 200 | `auth.forbidden` | admin |
| `/api/providers/price-catalogs/{catalog_id}/publish` | POST | `GovernedActionRequest` | `ProviderPriceCatalog` | 200 | `auth.forbidden` | admin |
| `/api/providers/price-catalogs/{catalog_id}/deprecate` | POST | `GovernedActionRequest` | `ProviderPriceCatalog` | 200 | `auth.forbidden` | admin |
| `/api/providers/usage` | GET | `ProviderUsageQuery` | `ProviderUsageReport` | 200 | `auth.unauthorized` | viewer |
| `/api/providers/balances` | GET | `ProviderBalanceQuery` | `ProviderBalanceReport` | 200 | `provider.auth_failed` | admin |
| `/api/providers/reconcile-billing` | POST | `ReconcileBillingRequest` | `ReconcileBillingResponse` | 202 | `provider.remote_failed` | admin |

### 34.5 Case Agent / Case Evolution

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/cases/{case_id}/agent/source-bindings` | GET | - | `PageResponse[CaseAgentSourceBinding]` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/agent/source-bindings` | POST | `CreateSourceBindingRequest` | `CaseAgentSourceBinding` | 201 | `validation.invalid_options` | operator |
| `/api/cases/{case_id}/agent/import-source` | POST | `ImportCaseSourceRequest` | `CaseAgentRun` | 202 | `provider.quota_exceeded` | operator |
| `/api/cases/{case_id}/agent/runs` | POST | `StartCaseAgentRunRequest` | `CaseAgentRun` | 202 | `validation.missing_case` | operator |
| `/api/cases/{case_id}/agent/runs` | GET | `CaseAgentRunQuery` | `PageResponse[CaseAgentRun]` | 200 | `auth.unauthorized` | viewer |
| `/api/cases/{case_id}/agent/runs/{run_id}` | GET | - | `CaseAgentRunDetail` | 200 | `auth.unauthorized` | viewer |
| `/api/cases/{case_id}/agent/drafts` | GET | `ScriptDraftQuery` | `PageResponse[ScriptDraft]` | 200 | `auth.unauthorized` | viewer |
| `/api/cases/{case_id}/agent/drafts/{draft_id}/adopt` | POST | `AdoptScriptDraftRequest` | `ScriptVersion` | 201 | `validation.invalid_options` | operator |
| `/api/cases/{case_id}/agent/memory-proposals` | GET | `MemoryProposalQuery` | `PageResponse[MemoryProposal]` | 200 | `auth.unauthorized` | viewer |
| `/api/cases/{case_id}/knowledge` | GET | - | `CaseKnowledgeResponse` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/memory` | GET | - | `PageResponse[CaseMemory]` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/memory/{memory_id}/approve` | POST | `ApproveMemoryRequest` | `CaseMemory` | 200 | `auth.forbidden` | operator |
| `/api/cases/{case_id}/memory/{memory_id}/reject` | POST | `RejectMemoryRequest` | `MemoryProposal` | 200 | `auth.forbidden` | operator |
| `/api/cases/{case_id}/performance` | GET | `CasePerformanceQuery` | `CasePerformanceResponse` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/metrics/import` | POST | `MetricsImportRequest` | `ImportBatchReport` | 202 | `validation.invalid_options` | operator |
| `/api/cases/{case_id}/reflection-runs` | POST | `StartReflectionRunRequest` | `ReflectionRun` | 202 | `provider.quota_exceeded` | operator |
| `/api/cases/{case_id}/insights` | GET | - | `PageResponse[CaseInsightCard]` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/creative-patterns` | GET | - | `PageResponse[CreativePattern]` | 200 | `validation.missing_case` | viewer |
| `/api/cases/{case_id}/scripts/generate-with-memory` | POST | `GenerateScriptWithMemoryRequest` | `ScriptDraft` | 202 | `prompt.output_invalid` | operator |
| `/api/videos/{video_version_id}/performance-attribution` | GET | - | `PerformanceAttributionResponse` | 200 | `auth.unauthorized` | viewer |

### 34.6 Finished Videos / Publishing / Ops / Import

| Endpoint | Method | Request | Response | Status | Errors | Permission |
|---|---|---|---|---|---|---|
| `/api/cases/{case_id}/finished-videos` | GET | `FinishedVideoQuery` | `PageResponse[FinishedVideo]` | 200 | `validation.missing_case` | viewer |
| `/api/finished-videos/{id}` | GET | - | `FinishedVideoDetail` | 200 | `artifact.missing` | viewer |
| `/api/finished-videos/{id}/preview-url` | GET | - | `SignedUrlResponse` | 200 | `artifact.missing` | viewer |
| `/api/finished-videos/{id}/download` | GET | - | `SignedUrlResponse` | 200 | `artifact.missing` | viewer |
| `/api/finished-videos/{id}` | DELETE | - | `OkResponse` | 200 | `workflow.invalid_transition` | admin |
| `/api/finished-videos/{id}/editor-handoff` | POST | `CreateEditorHandoffRequest` | `EditorHandoffPackageArtifact` | 201 | `artifact.missing` | operator |
| `/api/finished-videos/{id}/jianying-draft` | POST | `CreateJianyingDraftRequest` | `JianyingDraftPackageArtifact` | 201 | `artifact.missing` | operator |
| `/api/publish/packages` | GET | `PublishPackageQuery` | `PageResponse[PublishPackage]` | 200 | `auth.unauthorized` | viewer |
| `/api/publish/packages` | POST | `CreatePublishPackageRequest` | `PublishPackage` | 201 | `artifact.missing` | operator |
| `/api/publish/batches` | GET | `PublishBatchQuery` | `PageResponse[PublishBatchVm]` | 200 | `auth.unauthorized` | viewer |
| `/api/publish/batches` | POST | `CreatePublishBatchRequest` | `PublishBatchVm` | 201 | `publish.failed` | operator |
| `/api/publish/batches/{batch_id}` | GET | - | `PublishBatchVm` | 200 | `auth.unauthorized` | viewer |
| `/api/publish/batches/{batch_id}/submit` | POST | `SubmitPublishBatchRequest` | `PublishBatchVm` | 202 | `publish.failed`, `provider.quota_exceeded` | operator |
| `/api/publish/items/{item_id}` | PATCH | `PatchPublishItemRequest` | `PublishBatchItemVm` | 200 | `validation.invalid_options` | operator |
| `/api/publish/attempts/{attempt_id}` | GET | - | `PublishAttemptDetail` | 200 | `auth.unauthorized` | viewer |
| `/api/ops/dashboard` | GET | `OpsDashboardQuery` | `OpsDashboardVm` | 200 | `auth.unauthorized` | viewer |
| `/api/ops/cost-rollups` | GET | `CostRollupQuery` | `PageResponse[CostRollup]` | 200 | `auth.unauthorized` | viewer |
| `/api/ops/yield-funnel` | GET | `YieldFunnelQuery` | `YieldFunnelResponse` | 200 | `auth.unauthorized` | viewer |
| `/api/ops/budgets` | GET | `BudgetQuery` | `PageResponse[Budget]` | 200 | `auth.unauthorized` | viewer |
| `/api/ops/budgets` | POST | `UpsertBudgetRequest` | `Budget` | 201 | `auth.forbidden` | admin |
| `/api/ops/budgets/{budget_id}` | PATCH | `PatchBudgetRequest` | `Budget` | 200 | `auth.forbidden` | admin |
| `/api/ops/alerts/{event_id}/ack` | POST | `AcknowledgeAlertRequest` | `OpsAlertEvent` | 200 | `auth.forbidden` | operator |
| `/api/ops/alerts/{event_id}/resolve` | POST | `ResolveAlertRequest` | `OpsAlertEvent` | 200 | `auth.forbidden` | operator |
| `/api/runs/{run_id}/quality-checks` | POST | `CreateQualityCheckRequest` | `ProductionQualityCheck` | 201 | `validation.invalid_options` | operator |
| `/api/finished-videos/{id}/quality-checks` | POST | `CreateQualityCheckRequest` | `ProductionQualityCheck` | 201 | `validation.invalid_options` | operator |
| `/api/approval-requests/{id}/approve` | POST | `ApprovalDecisionRequest` | `ApprovalRequest` | 200 | `auth.forbidden` | operator |
| `/api/approval-requests/{id}/reject` | POST | `ApprovalDecisionRequest` | `ApprovalRequest` | 200 | `auth.forbidden` | operator |
| `/api/audit/events` | GET | `AuditEventQuery` | `PageResponse[AuditEvent]` | 200 | `auth.forbidden` | admin |
| `/api/import/batches` | POST | `CreateImportBatchRequest` | `ImportBatchReport` | 202 | `validation.invalid_options`, `artifact.integrity_failed` | operator |
| `/api/import/batches/{batch_id}` | GET | - | `ImportBatchReport` | 200 | `auth.unauthorized` | viewer |

### 34.7 API DTO 最低 Schema / Alias 表

下列表覆盖 Matrix 中尚未在前文定义的 DTO。若某个 DTO 已在前文定义，本节可作为 alias；若冲突，以本节为最低字段。

```python
T = TypeVar("T")

class OkResponse(BaseModel):
    ok: bool = True
    request_id: str

class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total_hint: int | None = None
    request_id: str

class SignedUrlResponse(BaseModel):
    url: str
    expires_at: datetime
    request_id: str

class EventStreamTokenResponse(BaseModel):
    stream_url: str
    token: str
    expires_at: datetime
    request_id: str

class BaseListQuery(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None

class RegistrationCodePreview(BaseModel):
    id: str
    role: Literal["admin", "operator", "viewer"]
    status: Literal["active", "disabled", "expired"]
    max_uses: int | None = None
    used_count: int
    expires_at: datetime | None = None
    created_at: datetime

class CreateRegistrationCodeRequest(BaseModel):
    role: Literal["admin", "operator", "viewer"]
    max_uses: int | None = None
    expires_at: datetime | None = None

class UpdateRegistrationCodeRequest(BaseModel):
    status: Literal["active", "disabled", "expired"] | None = None
    expires_at: datetime | None = None

class UpdateMeRequest(BaseModel):
    display_name: str | None = None

class DisableSecretRequest(BaseModel):
    reason: str

class CaseListQuery(BaseListQuery):
    search: str | None = None
    owner_user_id: str | None = None

class CreateCaseRequest(BaseModel):
    name: str
    description: str | None = None
    industry: str | None = None
    product: str | None = None
    target_audience: str | None = None

class PatchCaseRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    product: str | None = None
    target_audience: str | None = None

class CaseListItem(BaseModel):
    id: str
    name: str
    owner_user_id: str | None
    updated_at: datetime
    active_memory_count: int = 0

class CaseDetail(CaseListItem):
    description: str | None = None
    industry: str | None = None
    product: str | None = None
    target_audience: str | None = None

CreateDigitalHumanVideoJobRequest = DigitalHumanVideoRequest

class CreateJobResponse(BaseModel):
    job: Job
    initial_run: WorkflowRun | None
    request_id: str

class CreateRunRequest(BaseModel):
    mode: Literal["new", "retry", "resume"] = "new"
    reason: str | None = None

class WorkflowRunResponse(BaseModel):
    run: WorkflowRun
    request_id: str

class JobDetailResponse(BaseModel):
    job: Job
    runs: list[WorkflowRun]
    latest_report_artifact_id: str | None = None

class RunDetailResponse(BaseModel):
    run: WorkflowRun
    node_runs: list[NodeRun]
    artifacts: list[ArtifactRef]

class RunActionResponse(BaseModel):
    run: WorkflowRun
    accepted: bool

class RunReportResponse(BaseModel):
    public_report: RunPublicReportArtifact
    debug_report: RunDebugReportArtifact | None = None

class RunArtifactsResponse(BaseModel):
    run_id: str
    artifacts: list[ArtifactRef]
    request_id: str

class CancelRunRequest(BaseModel):
    reason: str | None = None
    force: bool = False

class RetryRunRequest(BaseModel):
    reason: str | None = None

class ResumeRunRequest(BaseModel):
    reason: str | None = None
    reuse_valid_artifacts: bool = True

class MediaAssetQuery(BaseListQuery):
    case_id: str | None = None
    kind: str | None = None
    annotation_status: str | None = None

class CreateMediaAssetFromUploadRequest(BaseModel):
    upload_session_id: str
    case_id: str | None = None
    title: str
    tags: list[str] = []

class MediaAssetDetail(BaseModel):
    asset: MediaAssetRecord
    preview_url: str | None = None
    latest_annotation_id: str | None = None

class PatchAnnotationRequest(BaseModel):
    etag: str
    patch: AnnotationPatch

class RerunAnnotationRequest(BaseModel):
    provider_profile_id: str | None = None
    force: bool = False

class AnnotationRunResponse(BaseModel):
    asset_id: str
    run_id: str | None
    status: Literal["queued", "running", "completed", "failed"]

class VoiceProfile(BaseModel):
    id: str
    display_name: str
    source: Literal["builtin", "cloned", "designed"]
    provider_profile_id: str | None = None
    preview_artifact_id: str | None = None
    enabled: bool = True

class VoiceQuery(BaseListQuery):
    source: str | None = None
    enabled: bool | None = None

class CloneVoiceRequest(BaseModel):
    display_name: str
    reference_upload_session_id: str
    provider_profile_id: str | None = None

class DesignVoiceRequest(BaseModel):
    display_name: str
    prompt: str
    provider_profile_id: str | None = None

class VoicePreviewRequest(BaseModel):
    text: str
    provider_profile_id: str | None = None

class VoicePreviewResponse(BaseModel):
    voice_id: str
    audio_artifact: ArtifactRef
    duration_sec: float

class PatchVoiceRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None

class PromptTemplateQuery(BaseListQuery):
    status: str | None = None
    purpose: str | None = None

class PromptTemplateView(BaseModel):
    template: PromptTemplate
    published_version: PromptVersion | None = None

class PromptBindingQuery(BaseListQuery):
    case_id: str | None = None
    node_id: str | None = None

class PromptBindingView(BaseModel):
    binding: PromptBinding
    resolved_version: PromptVersion | None = None

class CreatePromptTemplateRequest(BaseModel):
    name: str
    purpose: str
    variables_schema_ref: PromptSchemaRef
    output_schema_ref: PromptSchemaRef

class CreatePromptVersionRequest(BaseModel):
    content: str
    changelog: str | None = None

class ApprovePromptVersionRequest(BaseModel):
    reason: str

class PublishPromptVersionRequest(BaseModel):
    reason: str

class RollbackPromptRequest(BaseModel):
    target_version_id: str
    reason: str

class CreatePromptBindingRequest(BaseModel):
    prompt_template_id: str
    prompt_version_id: str
    case_id: str | None = None
    node_id: str | None = None
    priority: int

class PatchPromptBindingRequest(BaseModel):
    prompt_version_id: str | None = None
    enabled: bool | None = None
    priority: int | None = None

class PromptExperimentQuery(BaseListQuery):
    prompt_template_id: str | None = None
    status: str | None = None

class CreatePromptExperimentRequest(BaseModel):
    prompt_template_id: str
    variants: list[str]
    traffic_split: dict[str, float]
    scope: PromptExperimentScope
    start_at: datetime | None = None
    end_at: datetime | None = None

class PatchPromptExperimentRequest(BaseModel):
    status: Literal["draft", "running", "stopped", "completed"] | None = None
    traffic_split: dict[str, float] | None = None
    end_at: datetime | None = None

class ProviderProfileQuery(BaseListQuery):
    provider_id: str | None = None
    capability: str | None = None
    environment: str | None = None

class CreateProviderProfileRequest(BaseModel):
    provider_id: str
    model_id: str
    capability: str
    display_name: str
    environment: Literal["local", "dev", "staging", "prod"]
    secret_ref: str | None = None
    options_schema_ref: ProviderOptionsSchemaRef
    default_options: dict[str, JsonValue] = {}

class PatchProviderProfileRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    secret_ref: str | None = None
    default_options: dict[str, JsonValue] | None = None

class TestProviderProfileRequest(BaseModel):
    sample_input: dict[str, JsonValue] = {}

class ProviderHealthCheckResponse(BaseModel):
    profile_id: str
    ok: bool
    latency_ms: int | None = None
    error: ProviderError | None = None

class PriceCatalogQuery(BaseListQuery):
    provider_id: str | None = None
    active_only: bool = False

class UpsertPriceCatalogRequest(BaseModel):
    catalog: ProviderPriceCatalog
    items: list[ProviderPriceItem]

class ProviderUsageQuery(BaseModel):
    window_start: datetime
    window_end: datetime
    provider_id: str | None = None
    case_id: str | None = None

class ProviderUsageReport(BaseModel):
    invocations: int
    estimated_cost: Money
    actual_cost: Money | None = None
    unpriced_invocation_count: int

class GovernedActionRequest(BaseModel):
    reason: str

class ProviderBalanceQuery(BaseModel):
    provider_id: str | None = None
    account_group: str | None = None
    environment: Literal["local", "dev", "staging", "prod"] | None = None

class ProviderBalanceItem(BaseModel):
    provider_id: str
    account_group: str | None = None
    balance: Money | None = None
    quota_remaining: float | None = None
    unit: str | None = None
    checked_at: datetime
    status: Literal["ok", "low", "unknown", "failed"]

class ProviderBalanceReport(BaseModel):
    items: list[ProviderBalanceItem]
    request_id: str

class ReconcileBillingRequest(BaseModel):
    provider_id: str | None = None
    window_start: datetime
    window_end: datetime
    dry_run: bool = False

class ReconcileBillingResponse(BaseModel):
    reconciliation_run_id: str
    status: Literal["queued", "running"]
    request_id: str

class CaseAgentRunQuery(BaseListQuery):
    status: str | None = None

class CreateSourceBindingRequest(BaseModel):
    source_type: Literal["url", "text", "file", "manual_note"]
    source_ref: str
    title: str | None = None

class ImportCaseSourceRequest(BaseModel):
    source_binding_id: str
    provider_profile_id: str | None = None

class StartCaseAgentRunRequest(BaseModel):
    goal: Literal["brief", "script_draft", "memory_proposal"]
    source_binding_ids: list[str] = []

class CaseAgentRunDetail(BaseModel):
    run: CaseAgentRun
    briefs: list[CreativeBrief] = []
    drafts: list[ScriptDraft] = []
    memory_proposals: list[MemoryProposal] = []

class ScriptDraftQuery(BaseListQuery):
    status: str | None = None

class AdoptScriptDraftRequest(BaseModel):
    title: str | None = None
    publish_content: str | None = None

class MemoryProposalQuery(BaseListQuery):
    status: str | None = None

class ApproveMemoryRequest(BaseModel):
    reason: str | None = None

class RejectMemoryRequest(BaseModel):
    reason: str

class CaseKnowledgeResponse(BaseModel):
    case_id: str
    memories: list[CaseMemory]
    recent_script_versions: list[ScriptVersion]
    recent_video_versions: list[VideoVersion]

class CasePerformanceQuery(BaseModel):
    window: Literal["24h", "3d", "7d", "30d"] = "7d"

class CasePerformanceResponse(BaseModel):
    metrics: PerformanceMetricView
    observations: list[PerformanceObservation]

class StartReflectionRunRequest(BaseModel):
    window: Literal["24h", "3d", "7d", "30d"] = "7d"
    force: bool = False

class GenerateScriptWithMemoryRequest(BaseModel):
    brief: str
    memory_ids: list[str] = []

class PerformanceAttributionResponse(BaseModel):
    video_version_id: str
    feature_vector: CreativeFeatureVector | None = None
    observations: list[PerformanceObservation]
    contributing_memories: list[CaseMemory] = []

class FinishedVideoQuery(BaseListQuery):
    case_id: str | None = None
    qc_status: str | None = None

class FinishedVideoDetail(BaseModel):
    finished_video: FinishedVideo
    video_version: VideoVersion | None = None
    publish_records: list[PublishRecord] = []

class CreateEditorHandoffRequest(BaseModel):
    format: Literal["zip", "folder_manifest"] = "zip"

class CreateJianyingDraftRequest(BaseModel):
    template_id: str | None = None

class PublishPackageQuery(BaseListQuery):
    case_id: str | None = None
    source_type: str | None = None

class CreatePublishPackageRequest(BaseModel):
    source_finished_video_id: str | None = None
    upload_artifact_id: str | None = None
    title: str
    description: str = ""

class PublishBatchQuery(BaseListQuery):
    status: str | None = None

class CreatePublishBatchRequest(BaseModel):
    publish_package_ids: list[str]
    platform_targets: list[str]

class SubmitPublishBatchRequest(BaseModel):
    dry_run: bool = False

class PatchPublishItemRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    selected: bool | None = None

class PublishAttemptDetail(BaseModel):
    attempt: PublishAttempt
    record: PublishRecord | None = None

class OpsDashboardQuery(BaseModel):
    window_start: datetime
    window_end: datetime

class CostRollupQuery(OpsDashboardQuery):
    group_by: Literal["case", "provider", "model", "prompt_version", "run", "job"] | None = None

class YieldFunnelQuery(OpsDashboardQuery):
    case_id: str | None = None

class YieldFunnelResponse(BaseModel):
    events: list[YieldFunnelEvent]
    true_yield_rate: float | None = None

class BudgetQuery(BaseListQuery):
    scope_type: str | None = None

class UpsertBudgetRequest(BaseModel):
    budget: Budget

class PatchBudgetRequest(BaseModel):
    limit: Money | None = None
    alert_threshold: float | None = None
    enabled: bool | None = None

class AcknowledgeAlertRequest(BaseModel):
    note: str | None = None

class ResolveAlertRequest(BaseModel):
    resolution: str

class CreateQualityCheckRequest(BaseModel):
    check_type: Literal["auto", "manual", "platform_feedback"] = "manual"
    result: Literal["passed", "failed", "warning", "manual_required"]
    reason_code: str | None = None
    evidence_artifact_id: str | None = None
    affects_true_yield: bool = True

class ApprovalDecisionRequest(BaseModel):
    reason: str

class AuditEventQuery(BaseListQuery):
    actor: str | None = None
    resource_type: str | None = None
    action: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None

class ImportBatchStatus(str, Enum):
    created = "created"
    running = "running"
    completed = "completed"
    failed = "failed"
    partially_failed = "partially_failed"

class CreateImportBatchRequest(BaseModel):
    import_type: Literal["case", "script", "media", "finished_video", "video_version", "publish_record", "performance", "prompt_seed", "provider_price"]
    rows_artifact_id: str | None = None
    rows: list[JsonValue] | None = None
    dry_run: bool = False
    idempotency_key: str | None = None

class ImportRowResult(BaseModel):
    row_index: int
    status: Literal["created", "skipped", "failed"]
    external_id: str | None = None
    internal_id: str | None = None
    error: NodeError | None = None

class ImportBatchReport(BaseModel):
    batch_id: str
    import_type: str
    status: ImportBatchStatus
    created_count: int
    skipped_count: int
    failed_count: int
    results: list[ImportRowResult]
    mapping_artifact_id: str | None = None
    request_id: str
```

Alias 表：

| DTO | Alias / Source |
|---|---|
| `AuthUser`, `SessionInfo`, `LoginRequest`, `RegisterRequest`, `AuthResponse`, `ChangePasswordRequest`, `AdminCreateUserRequest`, `AdminUpdateUserRequest` | 第 33.1 章 |
| `PrepareUploadRequest`, `UploadSession`, `CompleteUploadRequest`, `CompleteUploadResponse` | 第 33.3 章 |
| `SecretQuery` | `BaseListQuery + provider_id/environment/status filters` |
| `CreateSecretRequest`, `RotateSecretRequest`, `SecretPreview` | 第 11.3 章 |
| `MediaAssetRecord` | 第 5 章素材实体 |
| `AnnotationEditorVm`, `MediaAssetCard`, `PublishBatchVm`, `PublishBatchItemVm`, `OpsDashboardVm` | 第 30 章 ViewModel |
| `PromptVersionView` | `PromptVersion` plus approval/published metadata |
| `ProviderPriceCatalog`, `ProviderPriceItem`, `ProviderProfile`, `ProviderCapability` | 第 11 / 26 章 |
| `CaseAgentRun`, `CaseAgentSourceBinding`, `CreativeBrief`, `ScriptDraft` | 第 32.4 章 |
| `CaseInsightCard` | 第 16.2 章 |
| `FinishedVideo`, `PublishPackage`, `PublishRecord`, `VideoVersion`, `ScriptVersion`, `ReflectionRun`, `PerformanceObservation`, `CaseMemory`, `MemoryProposal` | 第 5 / 8 / 25 / 32 章 |

### 34.8 Matrix 验收

- 第 34 章出现的每个 endpoint 都必须在 OpenAPI 中存在；第 15、30、33 章仅作为需求来源，路径冲突时不得额外实现重复 endpoint。
- 每个 request/response schema 必须能在 `packages/core/contracts` 中找到定义或明确 alias。
- 前端只能使用 OpenAPI generated client，不允许绕开 schema 手写 fetch body。
- Contract tests 必须验证每个写接口的 2xx、主要 4xx、权限失败和 idempotency 行为。

