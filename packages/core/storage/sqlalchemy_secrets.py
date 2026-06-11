from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import (
    CreateSecretRequest,
    DisableSecretRequest,
    ErrorCode,
    RotateSecretRequest,
    SecretPreview,
    utcnow,
)
from packages.core.storage.database import SecretRow
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError


def secret_row_to_contract(row: SecretRow) -> SecretPreview:
    return SecretPreview(
        id=row.id,
        provider_id=row.provider_id,
        environment=row.environment,
        name=row.name,
        status=row.status,
        masked_value="********",
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def local_secret_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class SqlAlchemySecretRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_secrets(self, *, limit: int = 50) -> list[SecretPreview]:
        with self.session_factory() as session:
            statement = select(SecretRow).order_by(SecretRow.updated_at.desc()).limit(limit)
            return [secret_row_to_contract(row) for row in session.scalars(statement)]

    def create_secret(self, payload: CreateSecretRequest) -> SecretPreview:
        with self.session_factory() as session:
            row = SecretRow(
                id=new_id("sec"),
                provider_id=payload.provider_id,
                environment=payload.environment,
                name=payload.name,
                encrypted_value=local_secret_digest(payload.value),
                status="active",
                rotated_at=utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)

    def rotate_secret(self, secret_id: str, payload: RotateSecretRequest) -> SecretPreview:
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Secret not found.")
            row.encrypted_value = local_secret_digest(payload.value)
            row.rotated_at = utcnow()
            row.status = "active"
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)

    def disable_secret(self, secret_id: str, payload: DisableSecretRequest) -> SecretPreview:
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Secret not found.")
            row.status = "disabled"
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)
