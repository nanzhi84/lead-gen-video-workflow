from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Revision id kept <= 32 chars (alembic version_num column limit); the file name
# carries the fuller description, mirroring 0023 (id ``0023_drop_lipsync_adv_fields``
# / file ``0023_drop_lipsync_advanced_fields.py``).
revision = "0024_drop_out_strict_fields"
down_revision = "0023_drop_lipsync_adv_fields"
branch_labels = None
depends_on = None

_TABLE = "jobs"
# OutputOptions request-layer keys removed in issue #118: only width/height/fps
# are consumed by production nodes; the export/upload/keep/format toggles were
# dead request knobs.
_REMOVED_OUTPUT_KEYS = (
    "export_jianying_draft",
    "export_editor_handoff",
    "upload_to_oss",
    "keep_local_originals",
    "format",
)
# StrictnessOptions request-layer keys removed in issue #118: only
# strict_timestamps (NarrationAlignment) and portrait_insufficient_policy
# (PortraitPlanning) drive a node; the broll/bgm policies and the cost-pricing
# flag were never consumed.
_REMOVED_STRICTNESS_KEYS = (
    "broll_insufficient_policy",
    "bgm_unavailable_policy",
    "strict_cost_pricing",
)


def upgrade() -> None:
    """Strip the un-consumed Output/Strictness keys from jobs.request.

    ``OutputOptions.{export_jianying_draft,export_editor_handoff,upload_to_oss,
    keep_local_originals,format}`` and ``StrictnessOptions.{broll_insufficient_policy,
    bgm_unavailable_policy,strict_cost_pricing}`` were removed from the contract
    (issue #118): they were exposed on the request layer but never consumed by any
    production node. Existing ``digital_human_video`` jobs persisted these keys via
    ``model_dump`` (defaults included), so their stored ``request`` JSONB still
    carries them; under ``extra="forbid"`` a later
    ``DigitalHumanVideoRequest.model_validate(row.request)`` (see
    ``packages/production/sqlalchemy_mappers.py``) would raise on every such row.
    Drop the keys so stored rows validate against the slimmed contract.
    PostgreSQL-only (JSONB op); a no-op elsewhere (SQLite unit fixtures build their
    schema from metadata and never carry these keys).
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    op.execute(
        f"""
        update {_TABLE}
        set request = jsonb_set(
            request,
            '{{output}}',
            (request -> 'output')
                - 'export_jianying_draft'
                - 'export_editor_handoff'
                - 'upload_to_oss'
                - 'keep_local_originals'
                - 'format'
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'output') = 'object'
          and jsonb_exists_any(
              request -> 'output',
              array[
                  'export_jianying_draft',
                  'export_editor_handoff',
                  'upload_to_oss',
                  'keep_local_originals',
                  'format'
              ]
          )
        """
    )
    op.execute(
        f"""
        update {_TABLE}
        set request = jsonb_set(
            request,
            '{{strictness}}',
            (request -> 'strictness')
                - 'broll_insufficient_policy'
                - 'bgm_unavailable_policy'
                - 'strict_cost_pricing'
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'strictness') = 'object'
          and jsonb_exists_any(
              request -> 'strictness',
              array[
                  'broll_insufficient_policy',
                  'bgm_unavailable_policy',
                  'strict_cost_pricing'
              ]
          )
        """
    )


def downgrade() -> None:
    """Best-effort restore: re-seed the dropped keys with their old defaults.

    The keys are re-added with the contract's former defaults
    (``OutputOptions`` -> export/upload toggles ``true``, ``keep_local_originals``
    ``false``, ``format`` ``"mp4"``; ``StrictnessOptions`` -> the two policies
    ``"soft_degrade"``, ``strict_cost_pricing`` ``false``) only when absent; any
    value already present is preserved (defaults concatenated on the left so the
    stored block wins). Meaningful only alongside a code rollback that restores the
    contract fields. PostgreSQL-only; a no-op elsewhere.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    op.execute(
        f"""
        update {_TABLE}
        set request = jsonb_set(
            request,
            '{{output}}',
            '{{"export_jianying_draft": true, "export_editor_handoff": true, "upload_to_oss": true, "keep_local_originals": false, "format": "mp4"}}'::jsonb
                || (request -> 'output')
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'output') = 'object'
        """
    )
    op.execute(
        f"""
        update {_TABLE}
        set request = jsonb_set(
            request,
            '{{strictness}}',
            '{{"broll_insufficient_policy": "soft_degrade", "bgm_unavailable_policy": "soft_degrade", "strict_cost_pricing": false}}'::jsonb
                || (request -> 'strictness')
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'strictness') = 'object'
        """
    )
