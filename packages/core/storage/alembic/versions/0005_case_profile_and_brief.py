from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0005_case_profile_and_brief"
down_revision = "0004_artifacts_run_index"
branch_labels = None
depends_on = None


# (column_name, sqlalchemy type, nullable, server_default) for each table.
# ARRAY columns are NOT NULL with an empty-array server default so the add is safe
# on populated tables; nullable Text/String columns carry no default.
_CASE_COLUMNS = (
    ("key_selling_points", ARRAY(sa.String()), False, "{}"),
    ("ip_persona", sa.Text(), True, None),
    ("brand_voice", sa.Text(), True, None),
    ("strategy_tags", ARRAY(sa.String()), False, "{}"),
    ("brand_keywords", ARRAY(sa.String()), False, "{}"),
    ("competitor_names", ARRAY(sa.String()), False, "{}"),
)
_BRIEF_COLUMNS = (
    ("topic", sa.Text(), True, None),
    ("audience", sa.Text(), True, None),
    ("key_insights", ARRAY(sa.String()), False, "{}"),
    ("source_refs", ARRAY(sa.String()), False, "{}"),
    ("generated_by_run_id", sa.String(), True, None),
)


def _add_missing_columns(bind, table: str, columns) -> None:
    existing = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    for name, type_, nullable, server_default in columns:
        if name in existing:
            continue
        op.add_column(
            table,
            sa.Column(name, type_, nullable=nullable, server_default=server_default),
        )


def _drop_columns(bind, table: str, columns) -> None:
    existing = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    for name, *_ in columns:
        if name in existing:
            op.drop_column(table, name)


def upgrade() -> None:
    # 0001_initial_schema bootstraps the schema via Base.metadata.create_all(), which
    # already includes these columns on fresh databases (declared on CaseRow /
    # CreativeBriefRow). Inspect existing columns first so this migration is a no-op on
    # create_all DBs, while still applying on databases provisioned before the columns
    # were added to the models.
    bind = op.get_bind()
    _add_missing_columns(bind, "cases", _CASE_COLUMNS)
    _add_missing_columns(bind, "creative_briefs", _BRIEF_COLUMNS)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_columns(bind, "creative_briefs", _BRIEF_COLUMNS)
    _drop_columns(bind, "cases", _CASE_COLUMNS)
