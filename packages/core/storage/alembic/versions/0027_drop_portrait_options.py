from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Revision id kept <= 32 chars (alembic version_num column limit); the file name
# carries the fuller description, mirroring 0023/0024.
revision = "0027_drop_portrait_options"
down_revision = "0026_visual_kind_video"
branch_labels = None
depends_on = None

# Former ``PortraitOptions`` default, used only to best-effort restore the block
# on downgrade (meaningful only alongside a code rollback that re-adds the field).
_PORTRAIT_DEFAULT = (
    '{"template_mode": "agent", "specific_template_id": null, '
    '"template_sequence_ids": [], "rhythm_preset": "balanced"}'
)


def upgrade() -> None:
    """Strip the retired top-level ``portrait`` block from persisted requests/defaults.

    ``PortraitOptions`` (``template_mode`` / ``specific_template_id`` /
    ``template_sequence_ids`` / ``rhythm_preset``) was removed from the contract
    (issue #130): the template modes were never wired to a real "digital-human
    template" entity, and ``rhythm_preset`` was never consumed by any production
    node. The whole options block is deleted, so ``DigitalHumanVideoRequest`` and
    ``UserGenerationDefaults`` no longer carry a ``portrait`` field.

    Existing rows persisted the block via ``model_dump`` (defaults included):
    ``jobs.request`` carries a non-null ``"portrait": {...}`` for every
    ``digital_human_video`` job, and ``user_generation_defaults.settings`` carries
    ``"portrait": null`` for every saved defaults row. Under ``extra="forbid"`` a
    later ``model_validate(row)`` (see ``packages/production/sqlalchemy_mappers.py``
    and ``apps/api/services/auth.py``) would raise on every such row. Drop the key
    from both tables so stored rows validate against the slimmed contract.
    PostgreSQL-only (JSONB op); a no-op elsewhere (SQLite unit fixtures build their
    schema from metadata and never carry the key).
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("jobs"):
        op.execute(
            """
            update jobs
            set request = request - 'portrait'
            where type = 'digital_human_video'
              and jsonb_typeof(request) = 'object'
              and jsonb_exists(request, 'portrait')
            """
        )
    if inspector.has_table("user_generation_defaults"):
        op.execute(
            """
            update user_generation_defaults
            set settings = settings - 'portrait'
            where jsonb_typeof(settings) = 'object'
              and jsonb_exists(settings, 'portrait')
            """
        )


def downgrade() -> None:
    """Best-effort restore: re-add the ``portrait`` block only where absent.

    ``jobs.request`` gets the former ``PortraitOptions`` default object;
    ``user_generation_defaults.settings`` gets ``"portrait": null`` (its former
    dumped value, since the field defaulted to ``None``). Only added when absent so
    any stored value already present would win. Meaningful only alongside a code
    rollback that restores the contract field. PostgreSQL-only; a no-op elsewhere.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("jobs"):
        op.execute(
            f"""
            update jobs
            set request = jsonb_set(request, '{{portrait}}', '{_PORTRAIT_DEFAULT}'::jsonb)
            where type = 'digital_human_video'
              and jsonb_typeof(request) = 'object'
              and not jsonb_exists(request, 'portrait')
            """
        )
    if inspector.has_table("user_generation_defaults"):
        op.execute(
            """
            update user_generation_defaults
            set settings = jsonb_set(settings, '{portrait}', 'null'::jsonb)
            where jsonb_typeof(settings) = 'object'
              and not jsonb_exists(settings, 'portrait')
            """
        )
