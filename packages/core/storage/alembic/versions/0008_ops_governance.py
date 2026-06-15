from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0008_ops_governance"
down_revision = "0007_selection_reservations"
branch_labels = None
depends_on = None


# §9.2 / §9.4 / §9.8 governance schema additions. 0001_initial_schema bootstraps
# the whole schema via Base.metadata.create_all(), so on a FRESH database these
# tables/columns already exist (declared on the ORM rows). This migration is
# therefore written to be a no-op on create_all DBs while still applying on
# databases provisioned before the governance work landed — every add inspects
# existing columns/tables first.

# (column_name, sqlalchemy type, nullable, server_default) additions to existing tables.
_BUDGET_COLUMNS = (
    ("period", sa.String(), False, sa.text("'day'")),
)
_COST_ROLLUP_COLUMNS = (
    ("window_start", sa.DateTime(timezone=True), True, None),
    ("window_end", sa.DateTime(timezone=True), True, None),
)
_ALERT_EVENT_COLUMNS = (
    ("rule_id", sa.String(), True, None),
    ("triggered_at", sa.DateTime(timezone=True), True, None),
    ("resolved_at", sa.DateTime(timezone=True), True, None),
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


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()

    # ops_alert_rules — §9.2 REQUIRED table.
    if not _has_table(bind, "ops_alert_rules"):
        op.create_table(
            "ops_alert_rules",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("condition", sa.String(), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column("scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("channels", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("severity", sa.String(), nullable=False, server_default=sa.text("'warning'")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # failure_taxonomy — §9.2 REQUIRED table, §9.6 15 failure classes.
    if not _has_table(bind, "failure_taxonomy"):
        op.create_table(
            "failure_taxonomy",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("failure_class", sa.String(), nullable=False),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("case_id", sa.String(), nullable=True),
            sa.Column("node_id", sa.String(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("dedupe_key", sa.String(), nullable=True, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "idx_failure_taxonomy_class", "failure_taxonomy", ["failure_class", "created_at"]
        )
        op.create_index("idx_failure_taxonomy_run", "failure_taxonomy", ["run_id"])

    _add_missing_columns(bind, "budgets", _BUDGET_COLUMNS)
    _add_missing_columns(bind, "cost_rollups", _COST_ROLLUP_COLUMNS)
    _add_missing_columns(bind, "ops_alert_events", _ALERT_EVENT_COLUMNS)

    existing_alert_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("ops_alert_events")}
    if "idx_ops_alert_events_status" not in existing_alert_indexes:
        op.create_index(
            "idx_ops_alert_events_status", "ops_alert_events", ["status", "code"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_alert_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("ops_alert_events")}
    if "idx_ops_alert_events_status" in existing_alert_indexes:
        op.drop_index("idx_ops_alert_events_status", table_name="ops_alert_events")
    _drop_columns(bind, "ops_alert_events", _ALERT_EVENT_COLUMNS)
    _drop_columns(bind, "cost_rollups", _COST_ROLLUP_COLUMNS)
    _drop_columns(bind, "budgets", _BUDGET_COLUMNS)
    if _has_table(bind, "failure_taxonomy"):
        op.drop_table("failure_taxonomy")
    if _has_table(bind, "ops_alert_rules"):
        op.drop_table("ops_alert_rules")
