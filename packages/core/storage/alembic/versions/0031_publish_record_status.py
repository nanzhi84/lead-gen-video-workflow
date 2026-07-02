from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Revision id kept <= 32 chars (alembic version_num column limit).
revision = "0031_publish_record_status"
down_revision = ("0030_sync_editing_agent_prompt", "0030_sync_editing_agent_slots")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Normalize historical PublishRecord.status values to its coarse contract.

    PublishBatchItem.status legitimately uses detailed workflow values such as
    ``publish_failed`` and ``manual_review_ready``. Older SQL writes copied those
    values into ``publish_records.status``, whose contract is only
    draft/submitted/published/failed. Reading such rows through Pydantic raised a
    ValidationError and surfaced as 500s on case-rubric pages.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("publish_records"):
        return
    op.execute(
        """
        update publish_records
        set status = case
                when status in (
                    'uploaded',
                    'normalizing',
                    'asr_running',
                    'copy_running',
                    'cover_running',
                    'excluded'
                ) then 'draft'
                when status in (
                    'review_ready',
                    'manual_review_ready',
                    'publishing',
                    'scheduled'
                ) then 'submitted'
                when status in ('generation_failed', 'publish_failed') then 'failed'
                else status
            end,
            updated_at = now()
        where status in (
            'uploaded',
            'normalizing',
            'asr_running',
            'copy_running',
            'cover_running',
            'excluded',
            'review_ready',
            'manual_review_ready',
            'publishing',
            'scheduled',
            'generation_failed',
            'publish_failed'
        )
        """
    )


def downgrade() -> None:
    # The normalized statuses lose the original item-level detail by design.
    return
