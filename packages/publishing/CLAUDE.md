# packages/publishing

发布领域的持久化层（spec §13）：把发布物（package/batch/item/attempt/record）落库，按状态机推进，并产出 §9.5 漏斗事件。本包**只有仓储 + 行映射**，不含平台 adapter、文案/封面生成或真机驱动——那些逻辑在别处（如 `apps/api/services/publishing.py` 的内存 sandbox 服务）。

## 关键文件
- `sqlalchemy_repository.py` — `SqlAlchemyPublishingRepository`：package/batch/item/attempt 的 CRUD + `submit_batch` 状态机 + 漏斗事件落库（本包唯一入口，见 `__init__.py` 仅导出此类）。
- `sqlalchemy_mappers.py` — Row → contract VM 映射（package/item/batch/attempt/record/artifact）。

## 流程
- `create_package`（来自 finished video 或 upload artifact，二选一分支）→ `create_batch`（package × platform_targets 笛卡尔积建 item）→ `submit_batch`（逐 item 建 attempt）→ `attempt_detail` 查回。
- `submit_batch` 全程经 `assert_transition`（`publish_batch` / `publish_item` / `publish_attempt`，来自 `packages.core.contracts.state_machines`），非随意改状态。`dry_run` 走 `review_ready` / `manual_review_ready` 分支而非 `published`。

## 约定与坑
- 本包不做平台选择：attempt 的 `adapter_id` 硬编码为 `"sandbox.publish"`，无环境开关、无真机路径。
- 漏斗事件（`publish_started` / `published`，带 `dedupe_key`）在 submit 事务 commit **之后** best-effort 落库（`persist_funnel_event_rows`，来自 `packages.core.observability`）；否则 SQL 后端 `true_yield_rate` 结构性为 0。run/job/case 经 package 的 source finished video 回溯解析。

## 测试
- `tests/integration/test_sqlalchemy_publishing.py`（仓储 + 状态机 + 映射）
- `tests/api/test_publishing_funnel.py`、`tests/api/test_publish_batches_case_filter.py`（漏斗事件 / case 过滤，经 API 层）
