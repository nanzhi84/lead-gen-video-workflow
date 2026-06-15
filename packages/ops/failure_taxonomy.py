"""Thin re-export of the §9.6 failure-taxonomy classifier.

The classifier itself lives in ``packages.core.observability.failure_taxonomy`` so
the production runtime / node runner can classify a terminal failure WITHOUT
violating the §3.2 dependency rule (``production`` / ``core`` must never depend on
``ops``). This module re-exports the same names so the ops / API-layer importers
keep working unchanged.
"""

from __future__ import annotations

from packages.core.observability.failure_taxonomy import (
    classify_error_code,
    classify_funnel_event,
)

__all__ = ["classify_error_code", "classify_funnel_event"]
