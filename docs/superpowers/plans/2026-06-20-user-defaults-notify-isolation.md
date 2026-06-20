# 用户默认设置 + 浏览器通知 + 按创建者隔离 · 实现计划

> **For agentic workers:** 本计划由 **Workflow** 编排的实现子代理逐任务实现（顺序执行，主 agent 只把控架构与验收、不写实现代码）。每个任务自带测试闭环（TDD）；任务边界即「评审可独立通过/打回」的最小单元。Steps 用 `- [ ]`。

**Goal:** 让每个用户用自己的默认设置一键/批量生成视频；任务终态弹浏览器通知；视频/任务按创建者隔离（admin 看全部）。

**Architecture:** 复用已有鉴权（cookie + `current_user` + 角色）。隔离以 `job.created_by` 为归属键、Case 共享；`owner_user_id` 反范式化到 `finished_videos` 与 `yield_funnel_events` 并在写入路径双写。默认设置存新表 `user_generation_defaults`。批量走新服务端端点（per-item 容错、服务端合并默认）。通知复用概览终态检测 + Notification API + 批量归并。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Alembic / Temporal；React 18 + Vite + React Query；contract-first（OpenAPI → schema.d.ts）。

## Global Constraints（每个任务都隐含遵守）
- **Contract-first**：改任何契约形状后必须 `python scripts/export_openapi.py` 且 `(cd apps/web && npm run generate:api)`；`apps/web/src/api/schema.d.ts` 是生成物，**禁止手改**。
- DB 迁移**只**放 `packages/core/storage/alembic/versions/`；当前 head=`0017_secret_encrypted_value`；本计划新增 `0018`、`0019`，single head。
- 领域类型唯一来源 `packages/core/contracts`（Pydantic v2）。
- 隔离口径：归属键=`job.created_by`；**Case 不过滤**；operator/viewer 只看自己，**admin 永远看全部**（无切换、无 scope 参数）；越权返回 404。
- owner FK 一律 `nullable=True` + 索引；**本期不加 NOT NULL 约束**；owner FK `ondelete=SET NULL`。
- 无主资源（owner=NULL）：普通用户不可见，admin 可见。
- 批量上限 50；不做成本预估；不引入 BatchJob 实体/新 JobType；不做 Web Push。
- lint：ruff line-length 100。worker 是独立进程（改 production 节点需重启 worker；测试不受影响）。
- 验收门禁：`python -m pytest -q` 全绿；`scripts/ci_gate.sh` 通过。

---

## 任务分组与文件结构

- **Group A — 隔离（后端 + 迁移）**：T1 迁移与 ORM、T2 写入路径双写 owner、T3 隔离强制与概览过滤。
- **Group B — 默认设置**：T4 contract + 表 + CRUD API。
- **Group C — 批量**：T5 批量端点（含服务端合并默认）。
- **Group D — 契约与前端**：T6 OpenAPI 重生成、T7 前端（默认设置 UI + 批量 UI + 通知 hook）、T8 端到端验收。

文件职责映射见各任务 **Files**。

---

### Task 1: 迁移 0018 — `owner_user_id` 列 + 回填 + ORM 映射

**Files:**
- Create: `packages/core/storage/alembic/versions/0018_owner_user_id_isolation.py`
- Modify: `packages/core/storage/database.py`（`FinishedVideoRow`≈756、`YieldFunnelEventRow`≈883 各加列）
- Test: `tests/storage/test_migration_owner_user_id.py`（若无 storage 目录则放 `tests/api/`）

**Interfaces:**
- Produces:
  - `finished_videos.owner_user_id: str | None`（FK `users.id`，`ondelete=SET NULL`，索引 `ix_finished_videos_owner_user_id`）。
  - `yield_funnel_events.owner_user_id: str | None`（FK `users.id`，`ondelete=SET NULL`，索引 `ix_yield_funnel_events_owner_user_id`）。
  - ORM 行模型暴露 `owner_user_id` 属性供后续任务读写。

- [ ] **Step 1**：写迁移 `upgrade()`：`op.add_column` 两表加 `owner_user_id`（nullable）+ `create_index` + `create_foreign_key(ondelete="SET NULL")`；`downgrade()` 反向。
- [ ] **Step 2**：写回填 SQL（在同一迁移 `upgrade()` 末尾，用 `op.execute`）：
  - `UPDATE finished_videos fv SET owner_user_id = j.created_by FROM workflow_runs r JOIN jobs j ON r.job_id=j.id WHERE fv.run_id=r.id AND fv.owner_user_id IS NULL;`
  - yield_funnel_events 三级回填（按优先级，IS NULL 守卫）：① `run_id→runs.job_id→jobs.created_by`；② `job_id→jobs.created_by`；③ `finished_video_id→finished_videos.owner_user_id`。
- [ ] **Step 3**：`database.py` 两个 Row 类加 `owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)`。
- [ ] **Step 4**：测试——内存/SQLite create_all 后断言列存在；构造「job(created_by=U)→run→finished_video」回填后 `owner_user_id==U`；断链（run_id=NULL）保持 NULL。
- [ ] **Step 5**：`python -m pytest tests/.../test_migration_owner_user_id.py -q` 绿。
- [ ] **Step 6**：提交 `feat(storage): add owner_user_id to finished_videos and yield_funnel_events (0018)`。

---

### Task 2: 写入路径双写 owner（新行创建即落 owner）

**Files:**
- Modify: `packages/production/pipeline/nodes/export_finished_video.py`（创建 `FinishedVideo` 处）
- Modify: `packages/production/sqlalchemy_repository.py`（`_finished_video_row()`≈1727、funnel 持久化≈1668）
- Modify: `packages/core/observability/funnel.py`（`persist_funnel_event_rows()`≈245-267）
- Modify: `apps/api/services/imports.py`（导入 finished video / owner 赋值≈50,120）
- Test: `tests/production/test_owner_write_paths.py`

**Interfaces:**
- Consumes: Task 1 的 `owner_user_id` 列。
- Produces: 任何新创建的 `FinishedVideo` 与 `YieldFunnelEvent` 行均带正确 `owner_user_id`（来源：run/job 的 `created_by`；import 走导入者/显式 owner）。

- [ ] **Step 1**：测试先行——经导出节点产出的 finished video 行 `owner_user_id == 触发 run 的 job.created_by`；新 funnel 事件带 owner；导入路径写显式 owner。
- [ ] **Step 2**：`export_finished_video.py` 在构造 `FinishedVideo(...)` 时传 `owner_user_id`（从 run→job.created_by 取，节点已有 run/job 上下文；若仅有 run，经仓库查 job.created_by）。
- [ ] **Step 3**：`_finished_video_row()` 持久化新增列；`persist_funnel_event_rows()` 写 owner（按 run_id→job.created_by→...优先级，复用 Task1 回填同款逻辑，抽成 `_resolve_event_owner(...)` 私有函数避免重复）。
- [ ] **Step 4**：`imports.py` 把硬编码 owner 改为显式（导入者 user 或保留 `usr_admin`，与现状一致但集中可读）。
- [ ] **Step 5**：`python -m pytest tests/production/test_owner_write_paths.py -q` 绿。
- [ ] **Step 6**：提交 `feat(production): populate owner_user_id on write paths`。

---

### Task 3: 隔离强制 + 概览按创建者过滤

**Files:**
- Modify: `apps/api/services/jobs_runs.py`（`created_by`≈336 改 current_user；`case_run_cards`≈239 加过滤）
- Modify: `apps/api/services/annotation_batch.py:51`（`created_by` 改 current_user）
- Modify: `apps/api/dependencies.py` 或 `apps/api/common.py`（新增可见性 helper + owner resolver）
- Modify: `apps/api/services/ops.py`（`ops_dashboard`≈142 接受并下传 owner 过滤）
- Modify: `packages/ops/sqlalchemy_repository.py`（`yield_funnel()`≈366-393 加 `owner_user_id` 过滤）
- Modify: `apps/api/routers/ops.py`（≈13 加 `current_user` 依赖）、`apps/api/services/finished_videos.py` / `routers/finished_videos.py`（列表/详情/预览/下载授权）、`apps/api/services/jobs_runs.py`（run_detail/job_detail 授权）
- Test: `tests/api/test_creator_isolation.py`

**Interfaces:**
- Consumes: Task 1/2 的 owner 列与写入。
- Produces:
  - `visible_owner_filter(user: AuthUser) -> str | None`：admin→`None`（不过滤）；否则→`user.id`。放在 `apps/api/common.py`。
  - `assert_owner_or_404(user: AuthUser, owner_user_id: str | None) -> None`：admin 放行；`owner_user_id == user.id` 放行；否则 `raise HTTPException(404)`。
  - resolver：`finished_video_owner(request, video_id) -> str | None`、`run_owner(...)`、`job_owner(...)`。

- [ ] **Step 1**：测试先行（核心隔离断言）：
  - 用户 A 建 job/run/finished video；B 调 `case_run_cards`/finished-video 列表/概览计数**均不含** A 的；B 调 A 的 detail/preview/download → 404。
  - admin 调以上**包含**所有用户的。
  - 概览 `ops_dashboard` 处理中/已完成/失败计数：A 只数自己；admin 数全部。
- [ ] **Step 2**：`jobs_runs.py:336`、`annotation_batch.py:51` 的 `created_by="usr_admin"` 改为当前用户（从 request 取 `current_user`；service 签名按需加 `user` 入参，路由处 `require_role(...)` 已能拿 user）。
- [ ] **Step 3**：实现 `visible_owner_filter` / `assert_owner_or_404` / resolver（`common.py`）。
- [ ] **Step 4**：list 端点 SQL 层按 owner 过滤（`case_run_cards`、finished-video 列表、`yield_funnel`）；`ops_dashboard` 路由加 `current_user`、把 owner 过滤下传仓库。
- [ ] **Step 5**：detail/preview/download（job/run/finished-video）调 `assert_owner_or_404`。
- [ ] **Step 6**：确认 `list_cases`/case detail **未**加 owner 过滤（保持共享）——补一条测试断言 B 仍能看到 A 的 case。
- [ ] **Step 7**：`python -m pytest tests/api/test_creator_isolation.py -q` 绿 + 既有 api 测试不回归。
- [ ] **Step 8**：提交 `feat(api): enforce creator-based isolation; admin sees all`。

---

### Task 4: 用户生成默认设置（contract + 表 + CRUD API）

**Files:**
- Create: `packages/core/contracts/preferences.py`
- Modify: `packages/core/contracts/__init__.py`（re-export）
- Create: `packages/core/storage/alembic/versions/0019_user_generation_defaults.py`
- Modify: `packages/core/storage/database.py`（`UserGenerationDefaultsRow`）
- Modify: `apps/api/routers/auth.py`（加 2 路由）、`apps/api/services/auth.py`（CRUD）
- Modify: `packages/core/storage/repository.py`（内存后端支持，若 list/CRUD 需要）
- Test: `tests/api/test_user_generation_defaults.py`

**Interfaces:**
- Produces:
  - contract `UserGenerationDefaults`：字段 = `voice: VoiceOptions | None`, `portrait: PortraitOptions | None`, `broll: BrollOptions | None`, `lipsync: LipSyncOptions | None`, `subtitle: SubtitleOptions | None`, `bgm: BgmOptions | None`, `cover: CoverOptions | None`, `output: OutputOptions | None`, `strictness: StrictnessOptions | None`（全部 Optional，缺省即用系统默认）。**不含** case_id/script/title。
  - 表 `user_generation_defaults(id PK, user_id FK 唯一, preset_name str default "default", settings JSONB, created_at, updated_at)`。
  - `GET /api/auth/me/generation-defaults -> UserGenerationDefaults`（无记录→系统默认值）。
  - `PUT /api/auth/me/generation-defaults`（body=`UserGenerationDefaults`）→ upsert，返回保存值。
  - service：`get_my_generation_defaults(request) -> UserGenerationDefaults`、`put_my_generation_defaults(request, payload) -> UserGenerationDefaults`。

- [ ] **Step 1**：测试先行：未保存时 GET 返回系统默认；PUT 后 GET 回读一致；换 session（同 user）仍在；不同 user 互不可见。
- [ ] **Step 2**：写 `preferences.py` contract + `__init__.py` re-export。
- [ ] **Step 3**：`database.py` 加 `UserGenerationDefaultsRow`；迁移 0019 建表（含 `uq_user_generation_defaults_user_id`）。
- [ ] **Step 4**：service CRUD（SQL + 内存后端都覆盖）；路由 2 个（`require_role(viewer)` 即可，登录用户均可存自己的）。
- [ ] **Step 5**：`python -m pytest tests/api/test_user_generation_defaults.py -q` 绿。
- [ ] **Step 6**：提交 `feat(api): per-user generation defaults store + endpoints (0019)`。

---

### Task 5: 批量生成端点

**Files:**
- Modify: `packages/core/contracts/jobs.py`（加 `BatchDigitalHumanVideoRequest` / `BatchItem` / `BatchGenerationResponse` / `BatchItemResult`）
- Modify: `apps/api/routers/jobs_runs.py`（加 `POST /api/jobs/digital-human-video/batch`）
- Modify: `apps/api/services/jobs_runs.py`（`create_digital_human_batch`；服务端合并默认；复用 `_start_submitted_run`）
- Test: `tests/api/test_digital_human_batch.py`

**Interfaces:**
- Consumes: Task 3 的 `created_by=current_user`；Task 4 的 `get_my_generation_defaults`。
- Produces:
  - `BatchItem`：`{script: str, title: str | None, script_version_id: str | None, overrides: dict | None}`（overrides 为 DigitalHumanVideoRequest 选项子集）。
  - `BatchDigitalHumanVideoRequest`：`{case_id: str, items: list[BatchItem], use_my_defaults: bool = True, settings: <内联选项> | None}`（`items` 长度 1..50）。
  - `BatchItemResult`：`{index: int, job_id: str | None, run_id: str | None, status: "created" | "failed", error: str | None}`。
  - `BatchGenerationResponse`：`{results: list[BatchItemResult]}`。
  - service `create_digital_human_batch(request, payload) -> BatchGenerationResponse`。

- [ ] **Step 1**：测试先行：3 条 items → 3 个独立 job/run；合并优先级 item.overrides > 我的默认 > 系统默认（断言落库 request 的字段）；第 2 条故意非法 → 该条 `failed` 其余 `created`；>50 条 → 422；每条 `created_by==当前用户`；item 级幂等键互不冲突。
- [ ] **Step 2**：contract 定义（`items` 用 `Field(min_length=1, max_length=50)`）。
- [ ] **Step 3**：service：循环/`asyncio.gather`+`Semaphore` 建 job→run；`_merge_options(item.overrides, my_defaults, system_default)`（抽公共 merge，深合并嵌套选项块）；item 级幂等 `f"{user.id}:{batch_key}:{index}"`；逐条 try/except 收集结果。
- [ ] **Step 4**：路由 `require_role(operator)`。
- [ ] **Step 5**：`python -m pytest tests/api/test_digital_human_batch.py -q` 绿。
- [ ] **Step 6**：提交 `feat(api): server-side batch digital-human-video endpoint`。

---

### Task 6: 重生成 OpenAPI 契约

**Files:**
- Modify（生成物）：`apps/web/src/api/openapi.json`、`apps/web/src/api/schema.d.ts`

**Interfaces:** 无新代码；把 Task 3/4/5 的契约变更同步到前端类型。

- [ ] **Step 1**：`python scripts/export_openapi.py`。
- [ ] **Step 2**：`(cd apps/web && npm run generate:api)`。
- [ ] **Step 3**：`git diff --stat apps/web/src/api/` 确认新端点/类型出现（generation-defaults、batch、owner 字段如有暴露）。
- [ ] **Step 4**：**不手改** schema.d.ts；如本机生成 key-order 与 CI 漂移，以 CI pinned venv 为准（见仓库约定，勿本机强改）。
- [ ] **Step 5**：提交 `chore(api): regenerate OpenAPI schema`。

---

### Task 7: 前端 — 默认设置 UI + 批量 UI + 通知 hook

**Files:**
- Modify: `apps/web/src/api/client.ts`（加 `api.me.getGenerationDefaults/putGenerationDefaults`、`api.jobs.createDigitalHumanVideoBatch`）
- Modify: `apps/web/src/pages/studio/StudioCreatePage.tsx`（保存/载入默认；批量改调新端点）
- Modify: `apps/web/src/components/studio-create/studioCreateModel.ts`（FormState ↔ UserGenerationDefaults 映射）
- Create: `apps/web/src/components/studio-create/SaveDefaultsButton.tsx`
- Create: `apps/web/src/components/studio-create/BatchScriptsModal.tsx`（粘贴/导入多条）
- Modify: `apps/web/src/components/script-tools/CandidatePoolModal.tsx`（多选 → 汇成 items 调批量端点）
- Create: `apps/web/src/hooks/useTaskNotifications.ts`
- Modify: `apps/web/src/pages/OverviewPage.tsx`（接入通知 hook + 权限开关）
- Test: `tests/frontend/test_user_defaults_batch_notify.py`（按现有 frontend 测试范式）

**Interfaces:**
- Consumes: Task 6 生成的类型；Task 4/5 端点。
- Produces:
  - `api.me.getGenerationDefaults()` / `putGenerationDefaults(payload)`；`api.jobs.createDigitalHumanVideoBatch(payload)`。
  - `useTaskNotifications({ runs, enabled })`：检测终态跳变，**不论聚焦**调 `new Notification`；多条归并为一条「N 完成 / M 失败」；`requestPermission` 仅由开关点击触发。
  - `mapFormToDefaults(form)` / `mapDefaultsToForm(defaults, base)`。

- [ ] **Step 1**：测试先行（按 `tests/frontend` 现有 python+交互范式）：保存默认→重载页表单回填；批量提交 N 条→调一次 batch 端点；通知开关点击触发权限请求；多终态归并一条。
- [ ] **Step 2**：client 加 3 个方法（用生成类型）。
- [ ] **Step 3**：SaveDefaultsButton + 进入 Studio 时 `getGenerationDefaults` hydrate（localStorage 兜底；首次登录把本地迁移上云）。
- [ ] **Step 4**：BatchScriptsModal（贴多条，每条可选标题）+ CandidatePoolModal 多选，两者都构造 `items` 调 `createDigitalHumanVideoBatch`，展示逐条结果。
- [ ] **Step 5**：`useTaskNotifications` + OverviewPage 接入（保留 toast；加「完成时通知我」开关绑定 `requestPermission`）。
- [ ] **Step 6**：`python -m pytest tests/frontend/test_user_defaults_batch_notify.py -q` 绿。
- [ ] **Step 7**：提交 `feat(web): generation defaults, batch UI, browser notifications`。

---

### Task 8: 端到端验收与门禁

**Files:** 无新增（修复型改动允许）。

- [ ] **Step 1**：`python -m pytest -q` 全量绿。
- [ ] **Step 2**：`scripts/ci_gate.sh`（按 worktree verify recipe：主仓 .venv + PYTHONPATH + symlink node_modules）通过。
- [ ] **Step 3**：人工核对验收清单（见 spec §9）：隔离/默认/批量/通知/契约不漂移。
- [ ] **Step 4**：若 OpenAPI 漂移仅本机 key-order 误报，按仓库约定忽略（CI venv 为准）。
- [ ] **Step 5**：提交剩余修复（如有）。

---

## Self-Review（对照 spec）
- **隔离**（spec §3）→ T1/T2/T3 覆盖（列+回填、写入双写、强制过滤与授权、概览计数、Case 不过滤断言）。✓
- **默认设置**（§4.1）→ T4 + T7（contract/表/CRUD + 前端保存载入）。✓
- **批量**（§4.2）→ T5 + T7（端点 + 双入口 UI、合并优先级、容错、上限 50、item 幂等）。✓
- **通知**（§5）→ T7（不论聚焦、归并、权限手势、特性检测）。✓
- **契约一致性**（§7）→ T6 + T8（重生成、漂移处理）。✓
- **范围外**（§8）→ 计划未含成本预估/Web Push/多预设切换/NOT NULL 收紧。✓
- **类型一致性**：`visible_owner_filter`/`assert_owner_or_404`/`UserGenerationDefaults`/`BatchDigitalHumanVideoRequest`/`BatchItemResult`/`useTaskNotifications`/`mapFormToDefaults` 命名跨任务一致。✓
