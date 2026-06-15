"""§9.2 ops_alert_rules engine + §9.8 alert types.

Evaluates ``OpsAlertRule`` rows against a metrics snapshot and emits
``OpsAlertEvent`` per §9.8. The 12 §9.8 alert types map to rule ``metric`` keys so
operators can declaratively configure thresholds without code changes:

* budget.spend_ratio       -> 预算超限
* cost.single_video        -> 单片成本异常
* provider.balance         -> Provider 余额低
* provider.failure_rate    -> Provider 失败率突增
* cost.unpriced            -> 价格表缺失或过期
* billing.reconcile_dev    -> 账单对账偏差
* yield.true_yield_rate    -> 成品率下降
* yield.qc_fail_rate       -> QC 不通过率升高
* cost.retry_cost          -> 重试成本异常
* prompt.version_regression-> Prompt 新版本效果劣化
* config.unapproved        -> 未审批配置进入生产
* audit.write_failure      -> 审计日志写入失败
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from packages.core.contracts import OpsAlertEvent, OpsAlertRule, utcnow

# The §9.8 alert-type catalog: metric key -> (default_code, human label). Used to
# seed default rules and to render messages.
ALERT_METRIC_CATALOG: dict[str, tuple[str, str]] = {
    "budget.spend_ratio": ("budget.exceeded", "预算超限"),
    "cost.single_video": ("cost.single_video_anomaly", "单片成本异常"),
    "provider.balance": ("provider.balance_low", "Provider 余额低"),
    "provider.failure_rate": ("provider.failure_rate_spike", "Provider 失败率突增"),
    "cost.unpriced": ("cost.unpriced", "价格表缺失或过期"),
    "billing.reconcile_deviation": ("billing.reconcile_deviation", "账单对账偏差"),
    "yield.true_yield_rate": ("yield.drop", "成品率下降"),
    "yield.qc_fail_rate": ("yield.qc_fail_rate_rise", "QC 不通过率升高"),
    "cost.retry_cost": ("cost.retry_anomaly", "重试成本异常"),
    "prompt.version_regression": ("prompt.version_regression", "Prompt 新版本效果劣化"),
    "config.unapproved": ("config.unapproved", "未审批配置进入生产"),
    "audit.write_failure": ("audit.write_failure", "审计日志写入失败"),
}


def _condition_met(condition: str, value: float, threshold: float) -> bool:
    if condition == "gt":
        return value > threshold
    if condition == "gte":
        return value >= threshold
    if condition == "lt":
        return value < threshold
    if condition == "lte":
        return value <= threshold
    if condition == "change_gt":
        # ``value`` is expected to already be the change magnitude for change_gt.
        return abs(value) > threshold
    return False


def evaluate_rules(
    rules: Iterable[OpsAlertRule],
    metrics: Mapping[str, float | None],
) -> list[OpsAlertEvent]:
    """Evaluate enabled rules against a metric snapshot, returning fired events.

    ``metrics`` maps a rule ``metric`` key to its current value. A rule fires when
    its metric is present, non-None, and its ``condition``/``threshold`` matches.
    Each fired rule yields one ``OpsAlertEvent`` whose ``id`` is deterministic
    (``alert_rule_<rule_id>``) so re-evaluation is idempotent at the row level."""

    events: list[OpsAlertEvent] = []
    now = utcnow()
    for rule in rules:
        if not rule.enabled:
            continue
        value = metrics.get(rule.metric)
        if value is None:
            continue
        if not _condition_met(rule.condition, float(value), float(rule.threshold)):
            continue
        code, label = ALERT_METRIC_CATALOG.get(rule.metric, (rule.metric, rule.metric))
        events.append(
            OpsAlertEvent(
                id=f"alert_rule_{rule.id}",
                code=code,
                rule_id=rule.id,
                status="open",
                severity=rule.severity,
                message=(
                    f"{label}: metric {rule.metric}={value:.4g} {rule.condition} "
                    f"threshold {rule.threshold:.4g}."
                ),
                triggered_at=now,
            )
        )
    return events
