from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_owner_user_id_isolation"
down_revision = "0018_xiaovmao_account_session"
branch_labels = None
depends_on = None


def _add_owner_column(inspector, table: str, index_name: str, fk_name: str, dialect: str) -> None:
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "owner_user_id" not in columns:
        op.add_column(table, sa.Column("owner_user_id", sa.String(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes(table)}
    if index_name not in indexes:
        op.create_index(index_name, table, ["owner_user_id"])
    # SQLite cannot ALTER TABLE to add a foreign key constraint; production is
    # Postgres where this is required for ondelete=SET NULL.
    if dialect != "sqlite":
        fks = {fk["name"] for fk in inspector.get_foreign_keys(table) if fk["name"]}
        if fk_name not in fks:
            op.create_foreign_key(
                fk_name,
                table,
                "users",
                ["owner_user_id"],
                ["id"],
                ondelete="SET NULL",
            )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    _add_owner_column(
        inspector,
        "finished_videos",
        "ix_finished_videos_owner_user_id",
        "fk_finished_videos_owner_user_id_users",
        dialect,
    )
    _add_owner_column(
        inspector,
        "yield_funnel_events",
        "ix_yield_funnel_events_owner_user_id",
        "fk_yield_funnel_events_owner_user_id_users",
        dialect,
    )

    # Backfill finished_videos owner from the run -> job.created_by chain.
    op.execute(
        sa.text(
            """
            UPDATE finished_videos AS fv
            SET owner_user_id = j.created_by
            FROM workflow_runs AS r
            JOIN jobs AS j ON r.job_id = j.id
            WHERE fv.run_id = r.id AND fv.owner_user_id IS NULL
            """
        )
    )

    # Backfill yield_funnel_events owner by priority: run -> job -> finished_video.
    op.execute(
        sa.text(
            """
            UPDATE yield_funnel_events AS e
            SET owner_user_id = j.created_by
            FROM workflow_runs AS r
            JOIN jobs AS j ON r.job_id = j.id
            WHERE e.run_id = r.id AND e.owner_user_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE yield_funnel_events AS e
            SET owner_user_id = j.created_by
            FROM jobs AS j
            WHERE e.job_id = j.id AND e.owner_user_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE yield_funnel_events AS e
            SET owner_user_id = fv.owner_user_id
            FROM finished_videos AS fv
            WHERE e.finished_video_id = fv.id AND e.owner_user_id IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    for table, index_name, fk_name in (
        (
            "yield_funnel_events",
            "ix_yield_funnel_events_owner_user_id",
            "fk_yield_funnel_events_owner_user_id_users",
        ),
        (
            "finished_videos",
            "ix_finished_videos_owner_user_id",
            "fk_finished_videos_owner_user_id_users",
        ),
    ):
        if dialect != "sqlite":
            fks = {fk["name"] for fk in inspector.get_foreign_keys(table) if fk["name"]}
            if fk_name in fks:
                op.drop_constraint(fk_name, table, type_="foreignkey")
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "owner_user_id" in columns:
            op.drop_column(table, "owner_user_id")
