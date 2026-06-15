"""§9.6 失败分类法 — pure ErrorCode / funnel-event -> FailureClass mapping.

This lives in ``packages.core.observability`` (NOT ``packages.ops``) so the
production runtime / node runner may classify a terminal failure WITHOUT violating
the §3.2 dependency rule (``production`` / ``core`` must never depend on ``ops``).
``packages.ops.failure_taxonomy`` re-exports these names so the ops/API importers
keep working.

§9.6 enumerates exactly 15 failure classes; ``classify_error_code`` maps an
``ErrorCode`` (or its string value) into one, falling back by prefix and finally
to ``provider_error`` so a terminal failure is NEVER dropped from the taxonomy.
"""

from __future__ import annotations

from packages.core.contracts import ErrorCode, FailureClass

_ERROR_CODE_TO_CLASS: dict[str, FailureClass] = {
    ErrorCode.provider_remote_failed.value: FailureClass.provider_error,
    ErrorCode.provider_auth_failed.value: FailureClass.provider_error,
    ErrorCode.provider_unsupported_option.value: FailureClass.provider_error,
    ErrorCode.provider_timeout.value: FailureClass.provider_timeout,
    ErrorCode.provider_quota_exceeded.value: FailureClass.quota_exceeded,
    ErrorCode.provider_cost_unpriced.value: FailureClass.price_missing,
    ErrorCode.prompt_render_error.value: FailureClass.prompt_render_error,
    ErrorCode.prompt_output_invalid.value: FailureClass.prompt_output_invalid,
    ErrorCode.prompt_version_not_published.value: FailureClass.prompt_output_invalid,
    ErrorCode.material_insufficient_portrait.value: FailureClass.material_insufficient,
    ErrorCode.material_insufficient_broll.value: FailureClass.material_insufficient,
    ErrorCode.material_annotation_failed.value: FailureClass.material_insufficient,
    ErrorCode.render_invalid_timeline.value: FailureClass.timeline_invalid,
    ErrorCode.render_failed.value: FailureClass.render_failed,
    ErrorCode.render_subtitle_failed.value: FailureClass.subtitle_failed,
    ErrorCode.publish_failed.value: FailureClass.publish_failed,
}

_PREFIX_TO_CLASS: tuple[tuple[str, FailureClass], ...] = (
    ("provider.", FailureClass.provider_error),
    ("prompt.", FailureClass.prompt_output_invalid),
    ("material.", FailureClass.material_insufficient),
    ("render.", FailureClass.render_failed),
    ("publish.", FailureClass.publish_failed),
)

_FUNNEL_EVENT_TO_CLASS: dict[str, FailureClass] = {
    "qc_failed": FailureClass.qc_failed,
    "manual_rejected": FailureClass.manual_rejected,
    "publish_failed": FailureClass.publish_failed,
}


def classify_error_code(error_code: str | None) -> FailureClass:
    """Classify an ErrorCode value (e.g. ``provider.timeout``) into a FailureClass.

    Unknown / missing codes degrade to ``provider_error`` (broadest external
    failure bucket) so a terminal failure is never dropped from the taxonomy."""

    if not error_code:
        return FailureClass.provider_error
    code = getattr(error_code, "value", error_code)
    mapped = _ERROR_CODE_TO_CLASS.get(code)
    if mapped is not None:
        return mapped
    for prefix, failure_class in _PREFIX_TO_CLASS:
        if code.startswith(prefix):
            return failure_class
    return FailureClass.provider_error


def classify_funnel_event(event_type: str | None) -> FailureClass | None:
    """Classify a §9.5 funnel failure event_type (qc_failed / manual_rejected /
    publish_failed). Returns ``None`` for non-failure event types."""

    if not event_type:
        return None
    return _FUNNEL_EVENT_TO_CLASS.get(event_type)
