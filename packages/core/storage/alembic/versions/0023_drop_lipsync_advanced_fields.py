from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Revision id kept <= 32 chars (alembic version_num column limit); the file name
# carries the fuller description, mirroring 0020 (id ``0020_resv_active_slot`` /
# file ``0020_selection_reservation_active_slot.py``).
revision = "0023_drop_lipsync_adv_fields"
down_revision = "0022_drop_publish_hashtags"
branch_labels = None
depends_on = None

_TABLE = "jobs"
_REMOVED_KEYS = ("ref_image_artifact_id", "video_extension", "query_face_threshold")


def upgrade() -> None:
    """Strip the un-wired advanced LipSync keys from jobs.request->'lipsync'.

    ``LipSyncOptions.{ref_image_artifact_id,video_extension,query_face_threshold}``
    were removed from the contract (issue #115): they were exposed on the request
    layer but never forwarded by the digital_human_v2 LipSync node, and
    ``query_face_threshold`` carried a unit mismatch. Existing
    ``digital_human_video`` jobs persisted these keys via ``model_dump`` (defaults
    included), so their stored ``request`` JSONB still carries them; under
    ``extra="forbid"`` a later ``DigitalHumanVideoRequest.model_validate(row.request)``
    (see ``packages/production/sqlalchemy_mappers.py``) would raise on every such
    row. Drop the keys so stored rows validate against the slimmed contract.
    PostgreSQL-only (JSONB op); a no-op elsewhere (SQLite unit fixtures build
    their schema from metadata and never carry these keys).
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
            '{{lipsync}}',
            (request -> 'lipsync')
                - 'ref_image_artifact_id'
                - 'video_extension'
                - 'query_face_threshold'
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'lipsync') = 'object'
          and jsonb_exists_any(
              request -> 'lipsync',
              array['ref_image_artifact_id', 'video_extension', 'query_face_threshold']
          )
        """
    )


def downgrade() -> None:
    """Best-effort restore: re-seed the dropped keys with their old defaults.

    The keys are re-added (``ref_image_artifact_id``/``query_face_threshold`` ->
    null, ``video_extension`` -> false) only when absent; any value already present
    on the lipsync block is preserved (defaults concatenated on the left so the
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
            '{{lipsync}}',
            '{{"ref_image_artifact_id": null, "video_extension": false, "query_face_threshold": null}}'::jsonb
                || (request -> 'lipsync')
        )
        where type = 'digital_human_video'
          and jsonb_typeof(request) = 'object'
          and jsonb_typeof(request -> 'lipsync') = 'object'
        """
    )
