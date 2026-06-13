from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_selection_ledger"
down_revision = "0002_provider_balance_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "selection_ledger",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("medium", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("slot_phase", sa.String(), nullable=False),
        sa.Column("diversity_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "case_id",
            "run_id",
            "medium",
            "asset_id",
            "slot_phase",
            name="uq_selection_ledger_case_id",
        ),
    )
    op.create_index("idx_selection_ledger_case_medium", "selection_ledger", ["case_id", "medium"])
    op.create_index("idx_selection_ledger_asset", "selection_ledger", ["medium", "asset_id"])


def downgrade() -> None:
    op.drop_index("idx_selection_ledger_asset", table_name="selection_ledger")
    op.drop_index("idx_selection_ledger_case_medium", table_name="selection_ledger")
    op.drop_table("selection_ledger")
