from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_selection_ledger_clip_id"
down_revision = "0011_finished_video_lipsync"
branch_labels = None
depends_on = None


_TABLE = "selection_ledger"
_UNIQUE_NAME = "uq_selection_ledger_case_id"
_OLD_UNIQUE_COLUMNS = ("case_id", "run_id", "medium", "asset_id", "slot_phase")
_NEW_UNIQUE_COLUMNS = ("case_id", "run_id", "medium", "asset_id", "clip_id", "slot_phase")
_CLIP_ID_COLUMN = ("clip_id", sa.String(), True, None)


def _add_missing_clip_id(bind) -> None:
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    name, type_, nullable, server_default = _CLIP_ID_COLUMN
    if name not in existing:
        op.add_column(
            _TABLE,
            sa.Column(name, type_, nullable=nullable, server_default=server_default),
        )


def _drop_clip_id(bind) -> None:
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    if _CLIP_ID_COLUMN[0] in existing:
        op.drop_column(_TABLE, _CLIP_ID_COLUMN[0])


def _unique_columns(bind) -> dict[str, tuple[str, ...]]:
    return {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in sa.inspect(bind).get_unique_constraints(_TABLE)
        if constraint["name"]
    }


def _ensure_unique(bind, columns: tuple[str, ...], *, nulls_not_distinct: bool) -> None:
    uniques = _unique_columns(bind)
    if uniques.get(_UNIQUE_NAME) == columns:
        return
    if _UNIQUE_NAME in uniques:
        op.drop_constraint(_UNIQUE_NAME, _TABLE, type_="unique")
    kwargs = {"postgresql_nulls_not_distinct": True} if nulls_not_distinct else {}
    op.create_unique_constraint(_UNIQUE_NAME, _TABLE, list(columns), **kwargs)


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    _add_missing_clip_id(bind)
    _ensure_unique(bind, _NEW_UNIQUE_COLUMNS, nulls_not_distinct=True)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    uniques = _unique_columns(bind)
    if _UNIQUE_NAME in uniques:
        op.drop_constraint(_UNIQUE_NAME, _TABLE, type_="unique")
    _drop_clip_id(bind)
    op.create_unique_constraint(_UNIQUE_NAME, _TABLE, list(_OLD_UNIQUE_COLUMNS))
