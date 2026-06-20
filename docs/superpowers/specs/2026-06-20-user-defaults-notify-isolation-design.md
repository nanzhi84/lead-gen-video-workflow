# 设计：用户默认设置 + 浏览器通知 + 按创建者隔离

- 日期：2026-06-20
- 工作树 base：`origin/main`（对齐于 `58a4fa1`）
- 交付方式：**一个整的 PR**（涵盖下述全部范围，不含可选的 Web Push）
- 决策来源：用户拍板 + 两轮独立架构评审（Codex）+ 仓库代码核实

## 1. 背景与现状（已核实）

系统已有完整鉴权层，三个需求都是「补全」而非从零：

- **鉴权**：`users` 表、`SessionRow`、HTTP-only cookie `cutagent_session`、角色 `admin/operator/viewer`。
  - `apps/api/dependencies.py:34` `current_user(request)` 从 cookie 解析 `AuthUser`。
  - `dependencies.py:38` `require_role(request, minimum)` 已有；`UserRole.admin` rank=30。
- **归属字段已就位（可空 FK → users.id）**：`JobRow.created_by`、`WorkflowRunRow.requested_by`、`CaseRow.owner_user_id`。
  - 归属链已天然贯通：`apps/api/services/jobs_runs.py:115` 把 `requested_by=job.created_by`。
- **隔离缺口**：
  - `jobs_runs.py:336` 创建 job 时 `created_by="usr_admin"` **硬编码**（另有 `annotation_batch.py:51`、`imports.py:50` 同类硬编码）。
  - `apps/api/services/ops.py` 的 `ops_dashboard` 无任何用户过滤（全局聚合）；`packages/ops/sqlalchemy_repository.py` 的 `yield_funnel()` 只按 `case_id`/时间窗过滤。
  - `case_run_cards` / `case_finished_videos` / `run_detail` / `job_detail` / finished-video 详情·预览·下载 **均无归属校验**（猜 ID 越权）。
  - `finished_videos` 表**没有用户列**（仅 `case_id`、可空 `run_id`）。
  - `yield_funnel_events` 表**无 user 维度**（有可空 `case_id/job_id/run_id`）。
  - 前端 `OverviewPage` 拉的是全局数据。
- **默认设置现状**：前端 `FormState` 已存 `localStorage`（`STORAGE_KEY=m6ar_studio_create_preferences_v1`，排除 title/script/scriptVersionId），仅本机、无后端。`DigitalHumanVideoRequest`（`packages/core/contracts/jobs.py`）是 per-job 契约，含 `voice/portrait/broll/lipsync/subtitle/bgm/cover/output/strictness` 嵌套选项；`buildJobPayload` 里 `provider_profile_id`、`strictness` 写死。
- **批量现状**：前端已有 client 侧串行循环（`StudioCreatePage.tsx:230-241` `batchCreateJobs` + `CandidatePoolModal`），无服务端端点、无单条容错、N 条共用一份 FormState、`created_by` 仍是 usr_admin。
- **通知现状**：`OverviewPage.tsx:41-53` 已在 15s 轮询里用 `previousStatuses` ref 检测终态跳变（succeeded/failed/cancelled）弹**页内 toast**；全仓**无浏览器 Notification API**；有 per-run websocket（`hooks/useRunEvents.ts`）但概览未用。
- **存量**：`usr_admin` 是真实 seed 用户（`repository.py:244`、`seed.py`）；`created_by` FK 为 `ondelete=SET NULL`。
- **迁移**：当前 alembic head = `0017_secret_encrypted_value`；本设计新增 `0018`、`0019`。

## 2. 决策（最终）

| # | 决策 | 取值 |
|---|------|------|
| 隔离口径 | 按**创建者**（`job.created_by`）隔离「视频/生成任务」；**Case 共享、不隔离** | 已定 |
| 可见性 | operator/viewer 只看自己；**admin 永远看全部（无切换、无 scope 参数）**；admin 自己创建的别人看不到 | 已定 |
| 默认设置 | **单一「我的默认」一套**（表内留 `preset_name` 便于日后扩多套） | 已定 |
| 批量入口 | **粘贴/导入多条** + **候选池多选** 两者都做，汇成同一批量端点 | 已定 |
| 通知触发 | **不论聚焦与否都弹**系统通知；批量**归并**成一条；保留 toast | 已定 |
| 成本预估 | **不做**（单条或批量都不加预估功能） | 已定 |
| Web Push | 关 tab 后送达 **本期不做**（可选 PR6，已剔出本 PR 范围） | 已定 |
| owner 存储 | 直接**反范式化** `owner_user_id` 到 `finished_videos` 与 `yield_funnel_events`（一个 PR 内做到位，不留 JOIN 临时态） | 已定 |

## 3. 需求 3：按创建者的「视频/任务」隔离

### 3.1 归属模型
- 归属键 = `job.created_by`（PR 内修正硬编码为当前用户）。链路：`job.created_by` →（赋值）`run.requested_by` → `finished_video.owner_user_id`（新增列）。
- Case **不隔离**：`list_cases`/case detail 保持对所有人可见。

### 3.2 可见性规则（统一函数）
- `resolve_visibility(user) -> owner_filter`：
  - `user.role == admin` → 不加 owner 过滤（看全部）。
  - 否则 → `owner_user_id == user.id`。
- list 端点在 **SQL 层**按该过滤；不做应用层后过滤。
- detail/预览/下载端点：取资源 owner，`owner == user.id` 或 `user` 为 admin 才放行，否则 404（不泄露存在性）。

### 3.3 owner 解析（处理断链）
- 三个 resolver：`job_owner(job_id)`、`run_owner(run_id)`、`finished_video_owner(video_id)`。
- `finished_videos.run_id` 可空（导入视频无 run、删 run 置空 `jobs_runs.py:604`）→ 直接读新列 `finished_videos.owner_user_id`（反范式化后不再依赖 JOIN）。
- 无主（owner 为 NULL，如历史无链路导入或 `SET NULL`）：普通用户**不可见**，admin 可见。

### 3.4 数据库（迁移 0018）
- `finished_videos` 增列 `owner_user_id`（可空 FK → users.id，建索引）。
- `yield_funnel_events` 增列 `owner_user_id`（可空，建索引）。
- 回填：
  - `finished_videos.owner_user_id` ← `run → job.created_by`（无链路则保持 NULL）。
  - `yield_funnel_events.owner_user_id` ← 优先 `run_id→job.created_by`，其次 `job_id→job.created_by`，再次 `finished_video_id→finished_videos.owner_user_id`；仍空保持 NULL（**不猜 case owner**）。
- 历史 `created_by="usr_admin"` 的链路天然回填到 admin，无需特殊处理。

### 3.5 写入路径双写 owner（创建即落 owner，不靠事后回填）
- 生产导出节点 `packages/production/pipeline/nodes/export_finished_video.py`：创建 `FinishedVideo` 时写 `owner_user_id = run/job.created_by`。
- SQL mapper `packages/production/sqlalchemy_repository.py` 的 `_finished_video_row()`：持久化 owner 列。
- funnel 持久化 `packages/core/observability/funnel.py` `persist_funnel_event_rows()`：事件落库时写 owner（来源同上优先级）。
- import 路径 `apps/api/services/imports.py`：显式写 owner（导入者或指定 admin）。

### 3.6 后端改动点
- 修 `created_by=current_user.id`：`jobs_runs.py:336`（并审计 `annotation_batch.py:51`、`imports.py` owner 赋值）。
- 新增可见性依赖/helper（集中在 `dependencies.py` 或 `apps/api/common.py`），各路由统一调用。
- list 端点加 owner 过滤：`case_run_cards`、finished-video 列表、job/run 列表、`ops_dashboard`/`yield_funnel`。
- `ops_dashboard` 路由补 `current_user` 依赖；概览处理中/已完成/失败计数随之只统计本人（admin 看全部）。
- detail/预览/下载端点加 owner 越权校验（admin 放行）。

### 3.7 前端
- 概览计数与最近任务：后端已过滤，前端无需传 user_id，天然变本人视图。
- admin 不需切换 UI（永远全部）。可选：概览顶部显示当前用户名/「全局视图」标识（admin），非必须。

## 4. 需求 1：用户默认设置 + 批量生成

### 4.1 用户默认设置
- 新契约模块 `packages/core/contracts/preferences.py`：`UserGenerationDefaults`，字段复用 `VoiceOptions/PortraitOptions/BrollOptions/LipSyncOptions/SubtitleOptions/BgmOptions/CoverOptions/OutputOptions/StrictnessOptions` 的子集；**不含** `case_id/script/title`。从 `contracts/__init__.py` re-export。
- 新表（迁移 0019）`user_generation_defaults(id, user_id FK 唯一, preset_name 默认 "default", settings JSONB, created_at, updated_at)`。
- 端点：`GET /api/auth/me/generation-defaults`、`PUT /api/auth/me/generation-defaults`（无则返回系统默认值）。
- **不扩** `DigitalHumanVideoRequest`（避免污染落库审计 JSONB）。
- 前端：Studio 加「保存为我的默认」按钮；登录/进入 Studio 时用服务端默认 hydrate `FormState`（localStorage 作兜底并一次性迁移上云）。

### 4.2 批量生成
- 新端点 `POST /api/jobs/digital-human-video/batch`：
  - 请求：`{items: [{script, title?, script_version_id?, overrides?}], defaults: "use_my_defaults" | <内联 settings>}`。
  - 响应：`{results: [{index, job_id?, run_id?, status: "created"|"failed", error?}]}`。
- 服务端 per-item：
  - 合并优先级 **item overrides > 我的默认 > 系统默认**（merge 逻辑在 service 层统一，不散到前端）。
  - 逐条容错（一条失败不回滚其余），逐条记录 created/failed。
  - 写正确 `created_by`。
  - **item 级幂等**：`user_id + batch_key + index`（现有中间件只做整请求级幂等，需 service 内自行处理）。
  - `asyncio.gather + semaphore` 控 Temporal 并发；复用 `_start_submitted_run`。
  - 一次上限 **50 条**（超限 422）。
- **不引入 BatchJob 实体、不新增 JobType**。
- 前端两个入口汇成 `items`：① 新「粘贴/导入多条脚本」录入界面（每条可带标题）；② 扩展 `CandidatePoolModal` 多选。替换现有脆弱 client 循环。
- 配好「我的默认」后，单条/批量都能**一键提交（用我的默认）**，实现「输入/生成脚本 → 生成视频，不用逐项点选」。

## 5. 需求 2：浏览器通知

- 复用 `OverviewPage` 已有终态检测（`previousStatuses`）。
- 新 `useTaskNotifications` hook：
  - 通过**用户手势**（设置开关/按钮）触发 `Notification.requestPermission()`（**不可**在 hook 初始化时调，否则被静默拒绝）。
  - 检测到终态即 `new Notification(...)`（**不论是否聚焦**），同时保留页内 toast。
  - 特性检测 `"Notification" in window`，权限被拒时回退仅 toast。
- **防风暴**：同一轮轮询出现多个终态 → 归并成一条「N 个完成 / M 个失败」系统通知，而非 N 条。
- 范围限制：轮询只在概览页可见时跑；关 tab 无送达路径 → Web Push 留后续（本期不做）。

## 6. 迁移与存量数据
- `usr_admin` 真实 seed，历史 `created_by="usr_admin"` 天然归 admin、admin 可见，无需特殊回填。
- owner FK `ondelete=SET NULL` → 可能无主产出 → 普通用户隐藏、admin 可见。
- 反范式化迁移本期一步到位（加可空列 + 回填 + 双写 + 查询切换）；**暂不**加 NOT NULL 约束（留后续收紧，避免历史 NULL 失败）。
- 迁移号：`0018`（owner 列 + 回填）、`0019`（user_generation_defaults 表）。

## 7. 契约一致性（contract-first）
- 任何契约变更后必须：`python scripts/export_openapi.py` → `(cd apps/web && npm run generate:api)`，CI 校验 `apps/web/src/api/openapi.json` + `schema.d.ts` 漂移。
- `schema.d.ts` 是生成物，**禁止手改**。
- 新增 contract 跨包改动（core → api → web）须在同一 PR 内三层一并提交。

## 8. 范围内 / 范围外
**范围内（本 PR）**：需求 3 创建者隔离（含 owner 反范式化与回填）、需求 1 默认设置 + 批量、需求 2 浏览器通知（轮询检测 + 归并）。
**范围外**：批量/单条成本预估；Web Push 后台送达（关 tab）；多命名预设切换 UI（仅预留 `preset_name` 列）；per-case 默认覆盖；团队/分组共享模型；NOT NULL 收紧迁移。

## 9. 验收标准（主 agent 负责）
- 单测：`python -m pytest -q` 全绿（含新增隔离/默认/批量测试）。
- 隔离：用户 A 创建的 job/run/finished video，用户 B 列表/详情/预览/下载/概览计数均**不可见**；admin 可见全部；猜 ID 访问他人资源返回 404。
- 默认：保存「我的默认」后换设备/重登仍生效；单条与批量都能用默认一键提交。
- 批量：N 条脚本一次提交生成 N 个独立 job/run，单条失败不影响其余，结果逐条可见；上限 50 生效。
- 通知：终态弹系统通知（不论聚焦）；批量归并成一条；权限请求由用户手势触发。
- 契约：OpenAPI/schema.d.ts 已重生成且 CI 不漂移；`schema.d.ts` 未手改。
- 门禁：`scripts/ci_gate.sh` 通过。
