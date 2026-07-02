from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_voice_case_bindings"
down_revision = "0031_publish_record_status"
branch_labels = None
depends_on = None

_TABLE = "voice_profiles"
_INDEX = "ix_voice_profiles_case_ids_gin"


def upgrade() -> None:
    """Bind synced/cloned provider voices to one or more cases."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if "case_ids" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "case_ids",
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default="{}",
            ),
        )
    op.execute(
        """
        update voice_profiles as voice
        set case_ids = matched.case_ids
        from (
            select
                voice_profiles.id as voice_id,
                array_agg(distinct cases.id order by cases.id) as case_ids
            from voice_profiles
            join cases
              on lower(btrim(voice_profiles.display_name)) = lower(btrim(cases.name))
            where cardinality(coalesce(voice_profiles.case_ids, '{}'::varchar[])) = 0
            group by voice_profiles.id
        ) as matched
        where cardinality(coalesce(voice.case_ids, '{}'::varchar[])) = 0
          and voice.id = matched.voice_id
        """
    )
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["case_ids"], postgresql_using="gin")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if "case_ids" in columns:
        op.drop_column(_TABLE, "case_ids")
