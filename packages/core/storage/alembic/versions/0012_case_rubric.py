from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_case_rubric"
down_revision = "0011_finished_video_lipsync"
branch_labels = None
depends_on = None


# case_rubric_v1: blind prediction, reward signals, retro, and bump proposals.
# Adds the case_rubric_v1 persistence loop:
#   - case_rubrics            (§6 executable scoring card, versioned)
#   - score_predictions       (§6.2 blind predictions; linked to reward labels)
#   - reward_signals          (§5 graded human-choice reward signals)
#   - rubric_bump_proposals   (§6.4 one-click upgrade proposals)
#
# Idempotent: 0001 bootstraps via Base.metadata.create_all(), so fresh DBs already
# have these tables. Inspect first so this migration is a no-op there but still
# applies on pre-existing databases.

_TIMESTAMP_COLUMNS = (
    sa.Column("schema_version", sa.String(length=16), nullable=False, server_default="v1"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)


def _case_fk(name: str = "case_id"):
    return sa.Column(name, sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)


def _existing_index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _index_where_kw(bind, where_sql: str | None) -> dict[str, object]:
    if where_sql is None:
        return {}
    if bind.dialect.name == "postgresql":
        return {"postgresql_where": sa.text(where_sql)}
    if bind.dialect.name == "sqlite":
        return {"sqlite_where": sa.text(where_sql)}
    return {}


def _ensure_index(
    bind,
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    where_sql: str | None = None,
) -> None:
    if table_name not in sa.inspect(bind).get_table_names():
        return
    if name in _existing_index_names(bind, table_name):
        return
    op.create_index(
        name,
        table_name,
        columns,
        unique=unique,
        **_index_where_kw(bind, where_sql),
    )


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if "case_rubrics" not in existing_tables:
        op.create_table(
            "case_rubrics",
            sa.Column("id", sa.String(), primary_key=True),
            _case_fk(),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("dimensions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("fitted_from_sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cold_start", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("supersedes_version", sa.Integer(), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
        op.create_index("idx_case_rubrics_case_status", "case_rubrics", ["case_id", "status"])

    if "score_predictions" not in existing_tables:
        op.create_table(
            "score_predictions",
            sa.Column("id", sa.String(), primary_key=True),
            _case_fk(),
            sa.Column("script_draft_id", sa.String(), nullable=True),
            sa.Column("script_version_id", sa.String(), nullable=True),
            sa.Column("rubric_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("composite", sa.Float(), nullable=False, server_default="0"),
            sa.Column("band", sa.String(), nullable=False, server_default="ok"),
            sa.Column("dimension_scores", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("settled_reward", sa.Float(), nullable=True),
            sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
        op.create_index("idx_score_predictions_case", "score_predictions", ["case_id"])
        op.create_index("idx_score_predictions_draft", "score_predictions", ["script_draft_id"])

    if "reward_signals" not in existing_tables:
        op.create_table(
            "reward_signals",
            sa.Column("id", sa.String(), primary_key=True),
            _case_fk(),
            sa.Column("script_version_id", sa.String(), nullable=True),
            sa.Column("script_draft_id", sa.String(), nullable=True),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("evidence_ref", sa.String(), nullable=True),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            *_TIMESTAMP_COLUMNS,
        )
        op.create_index("idx_reward_signals_case", "reward_signals", ["case_id"])

    if "rubric_bump_proposals" not in existing_tables:
        op.create_table(
            "rubric_bump_proposals",
            sa.Column("id", sa.String(), primary_key=True),
            _case_fk(),
            sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
            sa.Column("from_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("candidate", JSONB(), nullable=False),
            sa.Column("old_consistency", sa.Float(), nullable=False, server_default="0"),
            sa.Column("new_consistency", sa.Float(), nullable=False, server_default="0"),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
            *_TIMESTAMP_COLUMNS,
        )
        op.create_index("idx_rubric_bump_case_status", "rubric_bump_proposals", ["case_id", "status"])

    _ensure_index(bind, "idx_case_rubrics_case_status", "case_rubrics", ["case_id", "status"])
    _ensure_index(
        bind,
        "uq_case_rubrics_active_case",
        "case_rubrics",
        ["case_id"],
        unique=True,
        where_sql="status = 'active'",
    )
    _ensure_index(bind, "idx_score_predictions_case", "score_predictions", ["case_id"])
    _ensure_index(
        bind,
        "idx_score_predictions_draft",
        "score_predictions",
        ["script_draft_id"],
    )
    _ensure_index(bind, "idx_reward_signals_case", "reward_signals", ["case_id"])
    _ensure_index(
        bind,
        "uq_reward_signals_case_source_evidence",
        "reward_signals",
        ["case_id", "source_kind", "evidence_ref"],
        unique=True,
        where_sql="evidence_ref IS NOT NULL",
    )
    _ensure_index(
        bind,
        "idx_rubric_bump_case_status",
        "rubric_bump_proposals",
        ["case_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table in (
        "rubric_bump_proposals",
        "reward_signals",
        "score_predictions",
        "case_rubrics",
    ):
        if table in existing_tables:
            op.drop_table(table)
