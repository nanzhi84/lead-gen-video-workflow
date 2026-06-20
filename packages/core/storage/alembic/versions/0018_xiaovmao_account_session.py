from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_xiaovmao_account_session"
down_revision = "0017_secret_encrypted_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("publish_accounts")}
    for column in (
        "session_secret_ref",
        "session_status",
        "session_expires_at",
        "last_validated_at",
    ):
        if column in columns:
            op.drop_column("publish_accounts", column)
    if "xiaovmao_uid" not in columns:
        op.add_column("publish_accounts", sa.Column("xiaovmao_uid", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("publish_accounts")}
    if "xiaovmao_uid" in columns:
        op.drop_column("publish_accounts", "xiaovmao_uid")
    if "last_validated_at" not in columns:
        op.add_column(
            "publish_accounts",
            sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "session_expires_at" not in columns:
        op.add_column(
            "publish_accounts",
            sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "session_status" not in columns:
        op.add_column(
            "publish_accounts",
            sa.Column("session_status", sa.String(), nullable=False, server_default="never_logged_in"),
        )
    if "session_secret_ref" not in columns:
        op.add_column("publish_accounts", sa.Column("session_secret_ref", sa.String(), nullable=True))
