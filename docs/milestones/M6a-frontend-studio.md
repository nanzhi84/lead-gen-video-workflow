# M6a 施工简报：前端工作台修真（第一批）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6a-frontend-studio`
Spec：1A.6（行 165-172 前端选型）、第 16 章（路由与 ViewModel）、第 30 章（保真 ViewModel）、34.8（前端只允许用 OpenAPI 生成 client）。
用户要求（2026-06-11）：**以 Case 组织整个界面**；**用户友好、简洁**；**API key 等 provider 配置必须能在 Web 设置页直接完成**（用户暂不提供 key，后续自助配置）；实时进度。

## Goal

把占位前端替换为可用的 Case-first 工作台：登录 → Case 列表 → 进入单 Case 工作台
（创作/Runs 实时进度/成片）→ 设置页（providers/secrets/价格表）。
本批为 M6a-1；素材库/标注编辑器/发布中心/insights/ops 看板是 M6a-2（另行派发）。

## 关键设计决定（架构师已定，含视觉方向）

- 技术：React 18 + Vite + TS；`@tanstack/react-query`（已装）管 server state；`react-router-dom` v6（已装）
  + 集中式 typed route helpers（`routes.ts` 导出构造函数，组件不许手拼路径字符串）。
- API：只用 `src/api/schema.d.ts` 生成类型 + 一个薄 `fetchJson` 包装（带 credentials、统一错误体解析、
  Idempotency-Key 注入 helper）。禁止手写 response 形状（spec 34.8）。
- WS：M4 的 `GET /api/runs/{run_id}/events` 拿 token → `new WebSocket(/ws/runs/{id}?token=...)`；
  封装成 `useRunEvents(runId)` hook，断线重连 + 回放去重（event_id）。
- 视觉方向（防 AI 千篇一律）：中性浅色底、单一品牌色（深青 teal-700 系）、紧凑信息密度、
  无渐变无玻璃拟态；系统字体栈 + 等宽数字；状态用小色点 + 文本（succeeded 绿/failed 红/running 蓝/
  degraded 琥珀）；lucide-react 图标（已装）。布局：左侧窄边栏（Cases/素材库[占位]/发布[占位]/
  Ops[占位]/设置），主区顶部面包屑 + 内容。一切文案中文。
- 路由（spec 16.1 收敛到本批范围）：`/login`、`/studio`（Case 列表）、`/studio/:caseId`（工作台-创作）、
  `/studio/:caseId/runs`、`/studio/:caseId/finished-videos`、`/settings`（providers/secrets/prices 三个 tab）。
  占位路由（M6a-2）：`/library/*`、`/ops/*` 显示"建设中"骨架页。

## 改动清单（逐条核销）

### A. 应用骨架

- A1 路由 + 布局：边栏导航、面包屑、登录守卫（未登录 302 /login）、401 全局拦截回登录页。
- A2 QueryClient + `fetchJson`：统一错误体（spec 4.1）解析成 toast/inline 错误；`request_id` 显示在错误详情。
- A3 登录页：邮箱+密码，错误态（auth.invalid_credentials 文案化）；登录后跳 /studio。

### B. Case 列表与工作台

- B1 `/studio`：Case 卡片/表格（名称、更新时间、active_memory_count），新建 Case 弹窗（name/description/
  industry/product/target_audience），搜索过滤。
- B2 `/studio/:caseId` 创作页：脚本输入 + 标题 + 关键 options 表单（voice 选择、portrait 模式、
  broll/subtitle/bgm/cover 开关与参数，分组折叠、默认值跟随契约），提交创建 job（带 Idempotency-Key），
  成功后跳 runs 页并高亮新 run。
- B3 `/studio/:caseId/runs`：run 列表（状态、当前节点、进度、开始时间），行内动作 cancel/retry/resume
  （按 RunCard 的 canResume/canRetry 规则）；选中 run 展开节点时间线（node_runs + 状态 + 降级警告），
  **实时**：useRunEvents 驱动进度与节点状态更新，无需手动刷新。
- B4 `/studio/:caseId/finished-videos`：成片列表（标题、时长、QC 状态、创建时间），预览（preview-url）、
  下载、删除（admin）、"创建发布包"按钮（调用已有 API，跳转占位发布页）。

### C. 设置页（用户自助配置的核心）

- C1 `/settings` Providers tab：provider profile 列表（capability/model/environment/enabled/secret 绑定
  状态）、新建/编辑表单（按 CreateProviderProfileRequest 契约）、test 按钮（调 /test 端点显示延迟/错误）、
  启停开关。
- C2 Secrets tab：SecretPreview 列表（永不显示明文）、新建（provider/environment/name/明文输入一次性提交）、
  rotate（输入新明文+reason）、disable；操作后列表即时刷新。
- C3 Prices tab：价格表列表 + 查看 items；新建/审批/发布动作（admin，按钮带 reason 输入）。
- C4 设置页全部 admin 守卫（viewer/operator 只读或隐藏）。

### D. 工程

- D1 删除旧占位页中被替换的部分；保留 `/library/*`、`/ops/*` 占位骨架。
- D2 `npm run build` + `npx tsc --noEmit` 全绿；不引入新依赖（react-query/router/lucide 已装）。
- D3 后端如缺小接口（如 RunCard 所需字段聚合），允许加**只读** API（遵循契约规范、登记 OpenAPI、
  schema.d.ts 同步重新生成提交），不许改既有端点语义。

## 边界（Out of scope）

- 素材库五类页面、标注编辑器、发布中心完整页、insights/memory、ops 看板（M6a-2）；
- 真 provider/媒体语义（M6b/M6d）；移动端适配。

## Verification（sandbox 内）

- `cd apps/web && npx tsc --noEmit && npm run build`（node_modules 已由验收官预装，离线可用）。
- 后端测试不回退：`timeout -k 5 600 /home/nanzhi/projects/cutagent-genesis/.venv/bin/python -m pytest -q`。
- 若加了只读 API：OpenAPI 导出 + schema.d.ts 重新生成（openapi-typescript 离线可用）一并提交。

## 验收门（验收官执行）

1. 真后端起服（sqlalchemy + temporal）+ 前端 dev server，Playwright 走通：登录 → 建 Case →
   提交视频任务 → runs 页实时看到节点推进 → 成片出现可预览。
2. 设置页：新建 secret → 新建 provider profile 绑定该 secret → test 通过 → 禁用 secret 后 profile
   调度被拒（provider.auth_failed）。
3. 视觉抽查：case-first 导航、信息密度、无 AI 模板味；中文文案。
4. tsc/build 绿；后端全量测试不回退。
