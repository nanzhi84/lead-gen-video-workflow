from __future__ import annotations

# Compatibility bridge for databases that already recorded an earlier 0030 id.
# The current prompt sync lives in 0030_sync_editing_agent_prompt; this revision
# exists so those databases can be upgraded into the merged 0031 head.
revision = "0030_sync_editing_agent_slots"
down_revision = "0029_sync_editing_agent_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
