"""Single write helper for §9 yield-funnel lifecycle events.

The yield funnel records one row per lifecycle milestone of a run as it travels
from admission -> production -> finished video -> publish. Reads live in
``SqlAlchemyOpsRepository.yield_funnel`` (and the in-memory dashboard); writes go
through the in-memory ``Repository.record_yield_funnel_event`` which both stores
the event and persists it to ``yield_funnel_events`` on the next snapshot sync.

Before this helper, only ``workflow_succeeded`` (run completion) and
``finished_video_created`` were ever written, so the funnel had two stages out of
the dozen-odd milestones a run passes through. This module centralises the write
so every lifecycle call site emits with a consistent, deduped taxonomy and so a
failure to record a funnel event can NEVER break the pipeline (emission is
strictly best-effort — every call is wrapped in a guard that swallows and logs).

Taxonomy (authoritative — keep in lockstep with the locked ``funnel_taxonomy``):

* ``workflow_<RunStatus.value>`` — the run lifecycle family. ``RunStatus`` values
  are created / admitted / running / cancelling / succeeded / failed / cancelled,
  so the emitted strings are ``workflow_created``, ``workflow_admitted``,
  ``workflow_running``, ``workflow_cancelling``, ``workflow_succeeded``,
  ``workflow_failed`` and ``workflow_cancelled``. ``workflow_succeeded`` is
  load-bearing: ``true_yield_rate`` keys on it, so the string is preserved verbatim.
* ``finished_video_created`` — a finished video (and its publish package) is born.
* ``publish_package_created`` — a publish package is created independently.
* ``publish_attempt_submitted`` / ``publish_attempt_succeeded`` /
  ``publish_attempt_failed`` — the publish-attempt lifecycle.

``affects_true_yield`` is intentionally not threaded through here: the
``YieldFunnelEvent`` contract carries no such field and the DB column defaults to
True; the true-yield numerator is derived from ``event_type == 'workflow_succeeded'``
in the ops repository, not from a per-event flag.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from packages.core.storage import Repository

logger = logging.getLogger(__name__)


# The complete, authoritative set of funnel event strings this round emits.
# Kept as a frozenset so callers/tests can assert membership without importing
# the (str, Enum) RunStatus directly.
FUNNEL_TAXONOMY: frozenset[str] = frozenset(
    {
        "workflow_created",
        "workflow_admitted",
        "workflow_running",
        "workflow_cancelling",
        "workflow_succeeded",
        "workflow_failed",
        "workflow_cancelled",
        "finished_video_created",
        "publish_package_created",
        "publish_attempt_submitted",
        "publish_attempt_succeeded",
        "publish_attempt_failed",
    }
)


def workflow_stage(status) -> str:
    """Map a ``RunStatus`` (or its ``.value`` string) to its funnel event string.

    ``status`` may be a ``RunStatus`` enum member or a plain status string; both
    yield ``workflow_<value>`` (e.g. ``workflow_running``).
    """

    value = getattr(status, "value", status)
    return f"workflow_{value}"


def record_funnel_event(
    repository: "Repository",
    *,
    event_type: str,
    job_id: str | None = None,
    run_id: str | None = None,
    finished_video_id: str | None = None,
    publish_package_id: str | None = None,
    publish_attempt_id: str | None = None,
    dedupe_key: str | None = None,
    dedupe_aggregate_id: str | None = None,
    event_time: datetime | None = None,
) -> None:
    """Best-effort write of a single yield-funnel event.

    This is the ONE place lifecycle code should call to grow the funnel. It
    delegates to ``repository.record_yield_funnel_event`` (which dedupes on
    ``dedupe_key`` and persists on snapshot sync) but guarantees the call is
    non-fatal: any exception is logged and swallowed so a funnel write can never
    abort a run, a node, or a publish.

    ``dedupe_key`` follows the convention ``"<aggregate_id>:<event_type>"``. If
    not supplied, it is derived from ``dedupe_aggregate_id`` (falling back to the
    most specific id available: publish attempt -> publish package ->
    finished video -> run -> job).
    """

    if dedupe_key is None:
        aggregate_id = (
            dedupe_aggregate_id
            or publish_attempt_id
            or publish_package_id
            or finished_video_id
            or run_id
            or job_id
        )
        dedupe_key = f"{aggregate_id}:{event_type}"

    try:
        repository.record_yield_funnel_event(
            job_id=job_id,
            run_id=run_id,
            finished_video_id=finished_video_id,
            publish_package_id=publish_package_id,
            publish_attempt_id=publish_attempt_id,
            event_type=event_type,
            dedupe_key=dedupe_key,
            event_time=event_time,
        )
    except Exception:  # pragma: no cover - defensive: emission must never break flow
        logger.warning(
            "Failed to record yield funnel event %s (run=%s job=%s).",
            event_type,
            run_id,
            job_id,
            exc_info=True,
        )
