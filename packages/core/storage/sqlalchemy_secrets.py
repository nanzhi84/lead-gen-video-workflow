from __future__ import annotations

import base64

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
        secret_ref=row.secret_ref,
        status=row.status,
        rotated_from_secret_id=row.rotated_from_secret_id,
        rotated_at=row.rotated_at,
        disabled_at=row.disabled_at,
        masked_value="********",
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def local_dev_secret_envelope(value: str) -> str:
    # TODO(M2): replace this dev-only reversible envelope with an external secret store.
    return "dev+base64:" + base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


class SqlAlchemySecretRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_secrets(self, *, limit: int = 50) -> list[SecretPreview]:
        with self.session_factory() as session:
            statement = select(SecretRow).order_by(SecretRow.updated_at.desc()).limit(limit)
            return [secret_row_to_contract(row) for row in session.scalars(statement)]

    def create_secret(self, payload: CreateSecretRequest) -> SecretPreview:
        with self.session_factory() as session:
            secret_id = new_id("sec")
            row = SecretRow(
                id=secret_id,
                provider_id=payload.provider_id,
                environment=payload.environment,
                name=payload.name,
                secret_ref=f"dev://secrets/{secret_id}",
                encrypted_value=local_dev_secret_envelope(payload.plaintext_secret),
                status="active",
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
            rotated_at = utcnow()
            row.status = "rotated"
            row.rotated_at = rotated_at
            row.updated_at = utcnow()
            new_id_value = new_id("sec")
            new_row = SecretRow(
                id=new_id_value,
                provider_id=row.provider_id,
                environment=row.environment,
                name=row.name,
                secret_ref=f"dev://secrets/{new_id_value}",
                encrypted_value=local_dev_secret_envelope(payload.plaintext_secret),
                status="active",
                rotated_from_secret_id=row.id,
            )
            session.add(new_row)
            session.commit()
            session.refresh(new_row)
            return secret_row_to_contract(new_row)

    def disable_secret(self, secret_id: str, payload: DisableSecretRequest) -> SecretPreview:
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Secret not found.")
            row.status = "disabled"
            row.disabled_at = utcnow()
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)
