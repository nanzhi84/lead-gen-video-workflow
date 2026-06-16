# packages/ops

Ops / 可观测 / 治理域的持久化门面 + provider 余额轮询，支撑 Ops 控制台（spec §9 / §1.6，降级与成本必须显式上报而非隐藏）。本包是 CRUD + 简单聚合层，重计算（漏斗 taxonomy、true-yield 公式）都在 `packages.core.observability`，本包只调用/再导出。

## 职责
- 仓储门面：`SqlAlchemyOpsRepository`（`sqlalchemy_repository.py`）聚合 dashboard / provider usage / cost rollups / yield funnel / budgets / alerts / QC / approval / audit / billing reconcile。
- 成品率：`yield_funnel()` 读 §9.5 `YieldFunnelEventRow`，调 core 的 `compute_true_yield_rate`（run-scoped：去重 run，达 `published` 且未 `qc_failed`/`manual_rejected`）。
- 成本：`provider_usage()` 把 `ProviderInvocationRow.estimated_cost` 累加为 CNY；`provider_usage_metrics.py` 用 SQL 聚合 provider 成功率/成本。
- budget / alert：仅 list / upsert / patch / patch_status —— 本包**不**做阈值判定或告警规则求值（那是 production / API 层职责）。
- QC / approval：写库时顺带 stage 对应的 run-linked funnel 事件（`qc_*` / `manual_*`，best-effort 持久化）。
- Provider 余额：`balance/` 各家 poller 拉真实余额，graceful degrade（unconfigured/unsupported/unauthorized/error），绝不编造数字、绝不抛异常。

## 关键文件 / 子目录
- `sqlalchemy_repository.py` — 仓储门面，router `apps/api/routers/ops.py` 经 `apps/api/services/ops.py` 调它
- `sqlalchemy_mappers.py` — ORM Row -> contract 的纯转换函数
- `provider_usage_metrics.py` — SQL 聚合 provider 成功率/成本
- `funnel.py` — 再导出 `packages.core.observability.funnel` 的写助手（兼容老 import 路径）
- `balance/port.py` `registry.py` `service.py` `base.py` `providers/` — 余额 poller PORT / 分发(build_pollers,query_balance) / 聚合+可选后台轮询 / 共享助手 / 各家插件
- `__init__.py` — 出口（`SqlAlchemyOpsRepository` + funnel helpers）

## 约定与要求
- contract-first：输入输出一律 `packages.core.contracts` 类型，money 累加用 `Money.amount`、返回 CNY `Money`。
- §3.2 依赖规则：`production` / `core` 不得 import `ops`；漏斗与 true-yield 实现都在 `packages.core.observability`，本包只调用/再导出，勿在此重写。
- 余额 poller 失败映射为状态字段不抛异常；后台轮询默认 OFF（`settings.balance.poller_enabled`），无 key / 测试环境不外呼。

## 测试
- `pytest tests/ops` + `pytest tests/observability`（漏斗 / outbox / metrics）。

## 注意 / 坑
- `reconcile_billing` 当前只写审计并返回 `status="queued"`，未真正落对账结果——是占位，勿当成已完成对账。
- 改 Ops API contract 后须重新生成 openapi.json + schema.d.ts（`scripts/export_openapi.py`）。
