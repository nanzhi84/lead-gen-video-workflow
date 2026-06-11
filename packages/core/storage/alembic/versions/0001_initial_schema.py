from __future__ import annotations

from alembic import op
from sqlalchemy import text

from packages.core.storage.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
