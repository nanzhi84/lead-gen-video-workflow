from __future__ import annotations

from packages.core.contracts import RunStatus
from packages.core.storage import Repository


REQUIRED_LOG_FIELDS = (
    "request_id",
    "trace_id",
    "user_id",
    "case_id",
    "job_id",
    "run_id",
    "node_run_id",
    "provider_invocation_id",
    "prompt_invocation_id",
)


def span_name(kind: str, *parts: str) -> str:
    return ".".join([kind, *[part for part in parts if part]])


def metric_snapshot(repository: Repository) -> str:
    runs = list(repository.runs.values())
    node_runs = [node for nodes in repository.node_runs.values() for node in nodes]
    provider_invocations = list(repository.provider_invocations.values())
    failed_runs = len([run for run in runs if run.status == RunStatus.failed])
    failed_nodes = len([node for node in node_runs if node.status == "failed"])
    failed_providers = len([item for item in provider_invocations if item.status in {"failed", "timeout", "quota_exceeded"}])
    estimated_cost = sum(item.estimated_cost.amount for item in provider_invocations)
    lines = [
        "# HELP api_request_duration_seconds API request duration placeholder.",
        "# TYPE api_request_duration_seconds histogram",
        "api_request_duration_seconds_count 0",
        "# HELP api_request_errors_total API request errors.",
        "# TYPE api_request_errors_total counter",
        "api_request_errors_total 0",
        "# HELP workflow_run_duration_seconds Workflow run duration placeholder.",
        "# TYPE workflow_run_duration_seconds histogram",
        f"workflow_run_duration_seconds_count {len(runs)}",
        "# HELP node_run_duration_seconds Node run duration placeholder.",
        "# TYPE node_run_duration_seconds histogram",
        f"node_run_duration_seconds_count {len(node_runs)}",
        "# HELP node_run_retries_total Node run retries.",
        "# TYPE node_run_retries_total counter",
        "node_run_retries_total 0",
        "# HELP provider_invocation_duration_seconds Provider invocation duration placeholder.",
        "# TYPE provider_invocation_duration_seconds histogram",
        f"provider_invocation_duration_seconds_count {len(provider_invocations)}",
        "# HELP provider_invocation_failures_total Provider failures.",
        "# TYPE provider_invocation_failures_total counter",
        f"provider_invocation_failures_total {failed_providers}",
        "# HELP provider_cost_estimated_total Estimated provider cost.",
        "# TYPE provider_cost_estimated_total counter",
        f"provider_cost_estimated_total {estimated_cost}",
        "# HELP provider_unpriced_invocations_total Unpriced provider invocations.",
        "# TYPE provider_unpriced_invocations_total counter",
        "provider_unpriced_invocations_total 0",
        "# HELP yield_funnel_events_total Yield funnel events.",
        "# TYPE yield_funnel_events_total counter",
        f"yield_funnel_events_total {len(runs)}",
        "# HELP outbox_lag_seconds Outbox lag.",
        "# TYPE outbox_lag_seconds gauge",
        "outbox_lag_seconds 0",
        "# HELP temporal_activity_failures_total Temporal activity failures.",
        "# TYPE temporal_activity_failures_total counter",
        f"temporal_activity_failures_total {failed_nodes + failed_runs}",
    ]
    return "\n".join(lines) + "\n"

