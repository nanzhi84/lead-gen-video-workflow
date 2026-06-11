from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import CaseDetail, CaseListItem, CreateCaseRequest, PatchCaseRequest, utcnow
from packages.core.storage.database import CaseRow
from packages.core.storage.repository import new_id


def case_row_to_detail(row: CaseRow) -> CaseDetail:
    return CaseDetail(
        id=row.id,
        name=row.name,
        owner_user_id=row.owner_user_id,
        active_memory_count=0,
        description=row.description,
        industry=row.industry,
        product=row.product,
        target_audience=row.target_audience,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def case_row_to_list_item(row: CaseRow) -> CaseListItem:
    return CaseListItem(
        id=row.id,
        name=row.name,
        owner_user_id=row.owner_user_id,
        active_memory_count=0,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyCaseRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_cases(
        self,
        *,
        search: str | None = None,
        owner_user_id: str | None = None,
        limit: int = 50,
    ) -> list[CaseListItem]:
        with self.session_factory() as session:
            statement = select(CaseRow)
            if search:
                statement = statement.where(CaseRow.name.ilike(f"%{search}%"))
            if owner_user_id:
                statement = statement.where(CaseRow.owner_user_id == owner_user_id)
            statement = statement.order_by(CaseRow.updated_at.desc()).limit(limit)
            return [case_row_to_list_item(row) for row in session.scalars(statement)]

    def get_case(self, case_id: str) -> CaseDetail | None:
        with self.session_factory() as session:
            row = session.get(CaseRow, case_id)
            return case_row_to_detail(row) if row is not None else None

    def create_case(self, payload: CreateCaseRequest, *, owner_user_id: str) -> CaseDetail:
        with self.session_factory() as session:
            row = CaseRow(
                id=new_id("case"),
                name=payload.name,
                owner_user_id=owner_user_id,
                description=payload.description,
                industry=payload.industry,
                product=payload.product,
                target_audience=payload.target_audience,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return case_row_to_detail(row)

    def patch_case(self, case_id: str, payload: PatchCaseRequest) -> CaseDetail | None:
        with self.session_factory() as session:
            row = session.get(CaseRow, case_id)
            if row is None:
                return None
            for key, value in payload.model_dump(exclude_none=True).items():
                setattr(row, key, value)
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return case_row_to_detail(row)
