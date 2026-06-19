# M6Q 施工简报：Provider 观测（余额轮询 + 用量/API 监控）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6q-provider-observability`
来源：parity 审计两条真缺口——① Provider 真实余额轮询（genesis 现为 mock）；③ 平台用量/API 监控（provider_invocations 已记录但未聚合呈现，统计页「数据等待中」）。

## 已勘定事实（勿推翻）

- genesis 已有：`ProviderBalanceItem(provider_id, account_group, balance:Money, quota_remaining, unit, checked_at, status)` + `ProviderBalanceReport`（contracts ~1408-1426）；`GET /api/providers/balances`（routers/providers.py:109）→ service 返回 **mock**（services/providers.py:185-209）。**无 poller、无快照表、无 WS 广播、无前端 tab**。
- genesis 已记 `ProviderInvocation`（contracts 354-378：provider_id/model_id/capability_id/status/usage/billing_status/duration_ms/estimated_cost/started_at/finished_at）落 `provider_invocations` 表；`GET /api/providers/usage`、`GET /api/ops/cost-rollups` 已有。**缺**按 provider/capability/model 的 24h 调用数/成功率/成本聚合端点 + 前端监控视图。
- SecretStore（packages/core/storage/secret_store.py）存各家 key（profile.secret_ref 指向）。
- 原版余额 API 形状（参考 `/home/nanzhi/projects/digital-human-Cutagent/backend/app/services/balance/providers/`）：DeepSeek `GET /user/balance`→balance_infos[].total_balance；AliyunBSS SDK query_account_balance→available_cash_amount（覆盖 DashScope/Qwen）；OpenAI billing/subscription；Kimi 同 DeepSeek 式；HeyGem/RunningHub 自定义；MiniMax 无余额 API→status=unsupported。

## 改动清单

### A. 余额查询 + 轮询（后端）

- A1 余额查询插件：`packages/ai/providers/balance/`（每家一个小函数，经注入 httpx + SecretStore.get(secret_ref) 取 key），返回 `ProviderBalanceItem`（status ∈ ok/unconfigured/unsupported/unauthorized/error；balance:Money；checked_at）。先实现能拿到 key 的：dashscope（经 aliyun_bss 账户余额，或标 unsupported 待人工核）、runninghub.heygem、deepseek、kimi、openai（按原版形状）；minimax → unsupported。**无 key 的标 unconfigured，不报错**。HTTP 失败映射 error/unauthorized。
- A2 余额快照表 + 仓库：新增 `provider_balance_snapshots`（id, provider_id, account_group, balance_amount/currency, quota_remaining, unit, status, detail, checked_at, created_at）；sqlalchemy repo 加 upsert/读最新。alembic 迁移 + bootstrap schema 包含。
- A3 `services/providers.py` 的 `provider_balances()` 改为**读快照表最新**（替换 mock），无快照返回空+status pending。
- A4 刷新端点 `POST /api/providers/balances/refresh`：同步对各 profile 调余额插件 → 写快照 → 返回最新 report（操作员角色）。**不做常驻后台 poller 进程**（避免在 API 进程内挂长循环——干净起见用「按需刷新 + 可选 worker 定时」）；若要定时，留一个可被外部 cron/worker 调的 `refresh_all_balances()` 服务函数 + 文档说明，本批不起常驻线程。

### B. 用量/API 监控聚合（后端）

- B1 新增 `GET /api/ops/provider-usage-metrics?window_hours=24`：从 `provider_invocations` 聚合——按 provider_id × capability_id（可选 model_id）算 calls / success_count / success_rate / sum(estimated_cost) / p50?(可选) duration；返回 `ProviderUsageMetricsReport(items:[ProviderUsageMetricsItem(provider_id, capability_id, model_id, calls, success_rate, estimated_cost:Money, window_hours)], generated_at)`（新增契约）。sqlalchemy 聚合查询（group by），in-memory repo 给等价实现。
- B2 不新增 api_key_id 字段（genesis 不按外部 API-key 维度记，按 provider_profile/secret_ref 维度即可——更贴合 genesis 模型）。若要「逐 key」，用 provider_profile_id 维度（profile 即对应一把 key）。

### C. 前端（apps/web）

- C1 数据统计页（AnalyticsPage.tsx）新增 tab「余额&配额」：表格列各 provider 余额/配额/状态徽标/checked_at + 手动刷新按钮（调 /refresh）+ 60s 轮询（document.hidden 停）。状态用集中 i18n（ok/未配置/不支持/未授权/错误），不显示假数。
- C2 新增 tab「API 用量监控」：24h（可切 7/30 天）按 provider×capability 的调用数/成功率/估算成本表 + 纯 SVG 简单条形（沿用现有 analytics 组件风格），空态友好。
- C3 api client（api/r6.ts）加 providers.balances/refresh、ops.providerUsageMetrics；schema.d.ts 同步。

## 测试

- D1 余额插件 mock HTTP 单测（各状态映射）；快照 upsert/读最新单测；`/api/providers/balances` 读快照（非 mock）契约测试；refresh 端点 contract test。
- D2 provider-usage-metrics 聚合单测（构造若干 invocation，断言 calls/success_rate/cost 正确）。
- D3 `cd apps/web && npx tsc --noEmit && npm run build` 绿；OpenAPI/schema.d.ts 同步。
- D4 全量基线（约 200 单测）+ 新测不回退。所有 pytest 包 `timeout -k 5 600`，主仓 venv。DB 集成验收官在外面跑。

## 边界

- 不起常驻后台 poller 线程（按需刷新 + 可调函数；定时交给外部 worker/cron，文档说明）。
- 不做余额告警阈值（可后续接 OpsAlertEvent）。
- 不碰 pipeline/真出片；不动发布（M6c 冻结）。

## 验收门（验收官，真 key live）

1. /api/providers/balances/refresh 用真 key 拉到至少 DashScope/RunningHub 余额（或合理 unsupported/unconfigured），落快照、前端余额 tab 显示真数。
2. 跑过几条真 run 后，API 用量监控 tab 显示真实 provider×capability 24h 调用数/成功率/成本（非 0、非假）。
3. 全量 + DB + Temporal 三套绿；tsc/build 绿。
