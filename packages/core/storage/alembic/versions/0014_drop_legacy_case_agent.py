from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0014_drop_legacy_case_agent"
down_revision = ("0012_case_rubric", "0013_budget_enforce_reconcile")
branch_labels = None
depends_on = None

_LEGACY_TABLES = (
    "case_knowledge_items",
    "reflection_runs",
    "memory_proposals",
    "creative_briefs",
    "case_agent_runs",
    "case_agent_source_bindings",
)

_TIMESTAMP_COLUMNS = (
    sa.Column("schema_version", sa.String(length=16), nullable=False, server_default="v1"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _LEGACY_TABLES:
        if table in existing_tables:
            op.drop_table(table)


def downgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "case_agent_source_bindings" not in existing_tables:
        op.create_table(
            "case_agent_source_bindings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("source_ref", sa.Text(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
    if "case_agent_runs" not in existing_tables:
        op.create_table(
            "case_agent_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("goal", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("source_binding_ids", ARRAY(sa.String()), nullable=False, server_default="{}"),
            *_TIMESTAMP_COLUMNS,
        )
    if "creative_briefs" not in existing_tables:
        op.create_table(
            "creative_briefs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("source_binding_ids", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("topic", sa.Text(), nullable=True),
            sa.Column("audience", sa.Text(), nullable=True),
            sa.Column("key_insights", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("source_refs", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("generated_by_run_id", sa.String(), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
    if "memory_proposals" not in existing_tables:
        op.create_table(
            "memory_proposals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("memory_type", sa.String(), nullable=False, server_default="script_pattern"),
            sa.Column("scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("scope_key", sa.String(), nullable=True),
            sa.Column("insight", sa.Text(), nullable=False),
            sa.Column("evidence", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("supersedes_memory_id", sa.String(), nullable=True),
            sa.Column("proposed_by_reflection_run_id", sa.String(), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
    if "reflection_runs" not in existing_tables:
        op.create_table(
            "reflection_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("window", sa.String(), nullable=False),
            sa.Column("report_artifact_id", sa.String(), nullable=True),
            sa.Column("input_observation_ids", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("input_feature_vector_ids", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("memory_proposal_ids", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            *_TIMESTAMP_COLUMNS,
        )
    if "case_knowledge_items" not in existing_tables:
        op.create_table(
            "case_knowledge_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("ref_id", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("tags", ARRAY(sa.String()), nullable=False, server_default="{}"),
            sa.Column("embedding_ref", sa.String(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            *_TIMESTAMP_COLUMNS,
        )
        op.create_index("idx_knowledge_items_case_kind", "case_knowledge_items", ["case_id", "kind"])
