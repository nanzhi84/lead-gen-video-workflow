"""Single write helper for the §9.5 yield-funnel lifecycle taxonomy.

The yield funnel records one row per lifecycle milestone of a run as it travels
``submitted -> admitted -> started -> node_* -> finished_video_created ->
qc_* -> manual_* -> publish_* -> published``. Reads live in
``SqlAlchemyOpsRepository.yield_funnel`` (and the in-memory dashboard); writes go
through ``Repository.record_yield_funnel_event`` which both stores the event and
persists it to ``yield_funnel_events`` on the next snapshot sync.

This module lives in ``packages.core.observability`` (NOT ``packages.ops``) so
both the production runtime (``packages.production.pipeline`` / the node runner)
and the API layer (``apps/api``) may import it without violating the §3.2
dependency rule (``production`` must never depend on ``ops``). ``packages.ops``
re-exports the same names so existing ops/API importers keep working.

Taxonomy — authoritative, exactly the §9.5 set (spec 树影 v3 §9.5 成品率漏斗):

* run admission: ``submitted`` (run created) -> ``admitted`` (run admitted).
* run execution: ``started`` (run begins running).
* node runner: ``node_started`` / ``node_succeeded`` / ``node_failed`` (per node).
* finished video: ``finished_video_created``.
* quality check: ``qc_started`` / ``qc_passed`` / ``qc_failed``.
* manual review: ``manual_approved`` / ``manual_rejected``.
* publish: ``publish_started`` / ``published`` / ``publish_failed``.

成品率不得只看 workflow succeeded — the funnel distinguishes technical success
(``node_succeeded`` of the terminal node / ``finished_video_created``) from true
yield (a run that reached ``published`` and was not ``qc_failed`` / not
``manual_rejected``). The read side keys ``true_yield_rate`` on those strings.

Emission is strictly best-effort: every call is wrapped in a guard that swallows
and logs, so a funnel write can NEVER abort a run, a node, or a publish.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from packages.core.storage import Repository

logger = logging.getLogger(__name__)


# The complete, authoritative §9.5 funnel taxonomy. Kept as a frozenset so
# callers / tests can assert membership without importing this module's mapping
# helpers. These are the EXACT strings spec §9.5 requires in yield_funnel_events.
FUNNEL_TAXONOMY: frozenset[str] = frozenset(
    {
        "submitted",
        "admitted",
        "started",
        "node_started",
        "node_succeeded",
        "node_failed",
        "finished_video_created",
        "qc_started",
        "qc_passed",
        "qc_failed",
        "manual_approved",
        "manual_rejected",
        "publish_started",
        "published",
        "publish_failed",
    }
)

# Stages that, once recorded for a run, disqualify it from true yield even if it
# later reaches ``published`` (spec: "技术成功但 QC 不通过不能计入 true yield").
TRUE_YIELD_DISQUALIFIERS: frozenset[str] = frozenset({"qc_failed", "manual_rejected"})

# The terminal success stage that makes a run eligible for true yield.
TRUE_YIELD_SUCCESS: str = "published"


# Maps a ``RunStatus`` value to the §9.5 run-lifecycle string, where one exists.
# ``created -> submitted``, ``admitted -> admitted``, ``running -> started``.
# Terminal run statuses (succeeded / failed / cancelling / cancelled) are NOT in
# the §9.5 taxonomy: run-level technical success is observed via node/finished
# video stages, and failures via ``node_failed``. They map to ``None`` (no emit).
_RUN_STATUS_TO_STAGE: dict[str, str] = {
    "created": "submitted",
    "admitted": "admitted",
    "running": "started",
}

# Maps a ``NodeStatus`` value to its §9.5 node-lifecycle string. ``degraded`` is
# a successful node with warnings, so it counts as ``node_succeeded``. ``skipped``
# nodes did not actually execute and emit nothing.
_NODE_STATUS_TO_STAGE: dict[str, str] = {
    "succeeded": "node_succeeded",
    "degraded": "node_succeeded",
    "failed": "node_failed",
}


def workflow_stage(status) -> str | None:
    """Map a ``RunStatus`` (or its ``.value`` string) to its §9.5 funnel string.

    Returns the spec string (``submitted`` / ``admitted`` / ``started``) for the
    three run-lifecycle stages in the taxonomy, or ``None`` for terminal statuses
    that the §9.5 funnel does not track at run granularity.
    """

    value = getattr(status, "value", status)
    return _RUN_STATUS_TO_STAGE.get(value)


def node_stage(status) -> str | None:
    """Map a ``NodeStatus`` (or its ``.value`` string) to its §9.5 funnel string.

    Returns ``node_succeeded`` (succeeded / degraded), ``node_failed`` (failed),
    or ``None`` for non-terminal / skipped node statuses (no emission).
    """

    value = getattr(status, "value", status)
    return _NODE_STATUS_TO_STAGE.get(value)


def record_funnel_event(
    repository: "Repository",
    *,
    event_type: str,
    job_id: str | None = None,
    run_id: str | None = None,
    finished_video_id: str | None = None,
    publish_package_id: str | None = None,
    publish_attempt_id: str | None = None,
    node_run_id: str | None = None,
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
    most specific id available: node run -> publish attempt -> publish package ->
    finished video -> run -> job).
    """

    if dedupe_key is None:
        aggregate_id = (
            dedupe_aggregate_id
            or node_run_id
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


def compute_true_yield_rate(events) -> float | None:
    """Run-scoped true-yield rate over an iterable of ``YieldFunnelEvent``.

    Per spec §9.5, ``true_yield_rate`` must NOT be ``successes / total_events``
    (that denominator inflates as more event types are added). It is keyed on
    DISTINCT runs:

    * Denominator: distinct runs that entered the funnel (any event with a
      ``run_id``).
    * Numerator: distinct runs that reached ``published`` AND were never
      ``qc_failed`` / ``manual_rejected`` (技术成功但 QC 不通过不能计入 true yield).

    Returns ``None`` when no run-scoped events exist.
    """

    runs: set[str] = set()
    published_runs: set[str] = set()
    disqualified_runs: set[str] = set()
    for event in events:
        run_id = getattr(event, "run_id", None)
        if not run_id:
            continue
        runs.add(run_id)
        event_type = getattr(event, "event_type", None)
        if event_type == TRUE_YIELD_SUCCESS:
            published_runs.add(run_id)
        elif event_type in TRUE_YIELD_DISQUALIFIERS:
            disqualified_runs.add(run_id)
    if not runs:
        return None
    true_yield_runs = published_runs - disqualified_runs
    return len(true_yield_runs) / len(runs)


def resolve_event_owner(
    session,
    *,
    run_id: str | None,
    job_id: str | None,
    finished_video_id: str | None,
) -> str | None:
    """Resolve a funnel event's ``owner_user_id`` from its links, mirroring the 0018
    backfill priority: ``run_id → run.job_id → job.created_by`` then
    ``job_id → job.created_by`` then ``finished_video_id → finished_videos.owner_user_id``.

    Returns ``None`` when the chain is broken (no resolvable owner) so the row stays
    NULL (普通用户不可见、admin 可见) — never guesses a case owner.

    Takes the CALLER's session so the lookup joins the same uncommitted transaction
    (the funnel row and the job/run it links to may be written in one unit of work).
    """

    from sqlalchemy import select

    from packages.core.storage.database import (
        FinishedVideoRow,
        JobRow,
        WorkflowRunRow,
    )

    if run_id is not None:
        owner = session.scalar(
            select(JobRow.created_by)
            .join(WorkflowRunRow, WorkflowRunRow.job_id == JobRow.id)
            .where(WorkflowRunRow.id == run_id)
        )
        if owner is not None:
            return owner
    if job_id is not None:
        owner = session.scalar(select(JobRow.created_by).where(JobRow.id == job_id))
        if owner is not None:
            return owner
    if finished_video_id is not None:
        owner = session.scalar(
            select(FinishedVideoRow.owner_user_id).where(FinishedVideoRow.id == finished_video_id)
        )
        if owner is not None:
            return owner
    return None


def persist_funnel_event_rows(session_factory, events: list[dict]) -> None:
    """Best-effort, dedupe-safe persistence of §9.5 funnel rows for the SQL backend.

    The publish / quality-check / approval mutations on the SQL-backed repositories
    happen OUTSIDE the run/workflow snapshot sync that carries the production-pipeline
    stages (submitted/started/node_*/finished_video_created). Those repos therefore
    call this to land the ``published`` / ``qc_*`` / ``manual_*`` stages directly in
    ``yield_funnel_events`` — without them ``true_yield_rate`` would be structurally
    0.0 on the production backend even for fully published runs.

    Each ``event`` is a dict carrying ``event_type`` and ``dedupe_key`` plus any of
    ``job_id`` / ``run_id`` / ``finished_video_id`` / ``publish_package_id`` /
    ``publish_attempt_id`` / ``case_id`` / ``event_time``.

    Opens its OWN short transaction (never the caller's) so a funnel write can never
    abort or roll back the publish/QC/approval mutation, and skips any ``dedupe_key``
    that already exists so re-submits/re-decisions stay idempotent. Never raises —
    emission is strictly best-effort (spec §9.5)."""

    if not events:
        return
    try:
        from sqlalchemy import select

        from packages.core.contracts import utcnow
        from packages.core.storage.database import YieldFunnelEventRow
        from packages.core.storage.repository import new_id

        with session_factory() as session:
            for event in events:
                dedupe_key = event["dedupe_key"]
                existing = session.scalar(
                    select(YieldFunnelEventRow.id).where(
                        YieldFunnelEventRow.dedupe_key == dedupe_key
                    )
                )
                if existing is not None:
                    continue
                owner_user_id = event.get("owner_user_id") or resolve_event_owner(
                    session,
                    run_id=event.get("run_id"),
                    job_id=event.get("job_id"),
                    finished_video_id=event.get("finished_video_id"),
                )
                session.add(
                    YieldFunnelEventRow(
                        id=new_id("yield"),
                        case_id=event.get("case_id"),
                        job_id=event.get("job_id"),
                        run_id=event.get("run_id"),
                        finished_video_id=event.get("finished_video_id"),
                        publish_package_id=event.get("publish_package_id"),
                        publish_attempt_id=event.get("publish_attempt_id"),
                        owner_user_id=owner_user_id,
                        event_type=event["event_type"],
                        event_time=event.get("event_time") or utcnow(),
                        dedupe_key=dedupe_key,
                    )
                )
            session.commit()
    except Exception:  # pragma: no cover - defensive: emission must never break a flow
        logger.warning(
            "Failed to persist %d yield funnel event(s) to the DB.",
            len(events),
            exc_info=True,
        )
