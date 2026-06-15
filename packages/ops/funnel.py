"""Thin re-export of the §9.5 yield-funnel write helper.

The helper itself lives in ``packages.core.observability.funnel`` so the
production runtime and the node runner can import it WITHOUT violating the §3.2
dependency rule (``production`` / ``core`` must never depend on ``ops``;
``ops`` may depend on ``core``). This module re-exports the same names so the
ops / API-layer importers that historically did ``from packages.ops.funnel
import ...`` keep working unchanged.

New call sites should import from ``packages.core.observability`` directly.
"""

from __future__ import annotations

from packages.core.observability.funnel import (
    FUNNEL_TAXONOMY,
    compute_true_yield_rate,
    node_stage,
    record_funnel_event,
    workflow_stage,
)

__all__ = [
    "FUNNEL_TAXONOMY",
    "compute_true_yield_rate",
    "node_stage",
    "record_funnel_event",
    "workflow_stage",
]
