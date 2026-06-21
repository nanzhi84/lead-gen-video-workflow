from __future__ import annotations

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
from packages.core.storage.base_repository import BaseRepository
from packages.core.storage.database import AuditEventRow, SecretRow
from packages.core.storage.repository import new_id
from packages.core.storage.secret_store import SecretCipher, SecretStore
from packages.core.workflow import NodeExecutionError


def _add_secret_audit(
    session: Session,
    *,
    action: str,
    secret: SecretRow,
    actor: str | None,
) -> None:
    """Stage a secret governance audit event onto an OPEN session (spec §11.3 / §32.9).

    The row is added but NOT committed here so it shares the caller's transaction:
    either the mutation and its audit both persist, or neither does. The secret
    VALUE is never recorded — only resource metadata (secret_ref/provider/env).
    """
    session.add(
        AuditEventRow(
            id=new_id("audit"),
            actor=actor or "system",
            action=action,
            resource_type="secret",
            resource_id=secret.id,
            details={
                "secret_ref": secret.secret_ref,
                "provider_id": secret.provider_id,
                "environment": secret.environment,
            },
        )
    )


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


class SqlAlchemySecretRepository(BaseRepository):
    def __init__(self, session_factory: sessionmaker[Session], secret_store: SecretStore) -> None:
        super().__init__(session_factory)
        self.secret_store = secret_store
        self.cipher = SecretCipher.from_store(secret_store)

    def list_secrets(self, *, limit: int = 50) -> list[SecretPreview]:
        with self.session_factory() as session:
            statement = select(SecretRow).order_by(SecretRow.updated_at.desc()).limit(limit)
            return [secret_row_to_contract(row) for row in session.scalars(statement)]

    def create_secret(self, payload: CreateSecretRequest, *, actor: str | None = None) -> SecretPreview:
        with self.session_factory() as session:
            secret_id = new_id("sec")
            secret_ref = self.secret_store.put(payload.plaintext_secret, secret_ref=f"{secret_id}.secret")
            row = SecretRow(
                id=secret_id,
                provider_id=payload.provider_id,
                environment=payload.environment,
                name=payload.name,
                secret_ref=secret_ref,
                encrypted_value=self.cipher.encrypt(payload.plaintext_secret),
                status="active",
            )
            session.add(row)
            # Spec §32.9: the audit write joins the mutation transaction so an
            # audit failure rolls back the secret op (fail-closed governance).
            _add_secret_audit(session, action="secret.create", secret=row, actor=actor)
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)

    def rotate_secret(
        self, secret_id: str, payload: RotateSecretRequest, *, actor: str | None = None
    ) -> SecretPreview:
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Secret not found.")
            rotated_at = utcnow()
            row.status = "rotated"
            row.rotated_at = rotated_at
            row.updated_at = utcnow()
            new_id_value = new_id("sec")
            new_secret_ref = self.secret_store.put(payload.plaintext_secret, secret_ref=f"{new_id_value}.secret")
            new_row = SecretRow(
                id=new_id_value,
                provider_id=row.provider_id,
                environment=row.environment,
                name=row.name,
                secret_ref=new_secret_ref,
                encrypted_value=self.cipher.encrypt(payload.plaintext_secret),
                status="active",
                rotated_from_secret_id=row.id,
            )
            session.add(new_row)
            # Spec §32.9: audit + mutation persist atomically (same transaction).
            _add_secret_audit(session, action="secret.rotate", secret=new_row, actor=actor)
            session.commit()
            session.refresh(new_row)
            return secret_row_to_contract(new_row)

    def disable_secret(
        self, secret_id: str, payload: DisableSecretRequest, *, actor: str | None = None
    ) -> SecretPreview:
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Secret not found.")
            row.status = "disabled"
            row.disabled_at = utcnow()
            row.updated_at = utcnow()
            row.encrypted_value = None
            self.secret_store.disable(row.secret_ref)
            # Spec §32.9: audit + mutation persist atomically (same transaction).
            _add_secret_audit(session, action="secret.disable", secret=row, actor=actor)
            session.commit()
            session.refresh(row)
            return secret_row_to_contract(row)

    def read_secret(self, secret_id: str, *, actor: str | None = None) -> str | None:
        """Reveal a secret's plaintext value, recording a ``secret.read`` audit atomically.

        Spec §32.9: the read audit joins the same transaction as the reveal so the
        access is durably recorded before the value is returned. The secret VALUE is
        never written to the audit row. Returns ``None`` (and writes no audit) when
        the secret or its backing value is missing.
        """
        with self.session_factory() as session:
            row = session.get(SecretRow, secret_id)
            if row is None or not row.secret_ref:
                return None
            value = self._value_for_row(row)
            if value is None:
                return None
            _add_secret_audit(session, action="secret.read", secret=row, actor=actor)
            session.commit()
            return value

    def _value_for_row(self, row: SecretRow) -> str | None:
        if row.encrypted_value:
            value = self.cipher.decrypt(row.encrypted_value)
            if value is not None:
                return value
        return self.secret_store.get(row.secret_ref)


class SqlAlchemySecretStore:
    """SecretStore facade that reads provider secrets from encrypted DB rows.

    ``put`` and ``disable`` still delegate to the file-backed fallback so direct
    non-provider callers such as publishing sessions keep their existing behavior.
    SQL secret governance writes ``encrypted_value`` through
    :class:`SqlAlchemySecretRepository`.
    """

    def __init__(self, session_factory: sessionmaker[Session], fallback: SecretStore) -> None:
        self.session_factory = session_factory
        self.fallback = fallback
        self.cipher = SecretCipher.from_store(fallback)

    def put(self, plaintext: str, *, secret_ref: str | None = None) -> str:
        return self.fallback.put(plaintext, secret_ref=secret_ref)

    def get(self, secret_ref: str) -> str | None:
        with self.session_factory() as session:
            statement = (
                select(SecretRow)
                .where(SecretRow.secret_ref == secret_ref)
                .where(SecretRow.status == "active")
                .order_by(SecretRow.updated_at.desc())
                .limit(1)
            )
            row = session.scalars(statement).first()
            if row is not None and row.encrypted_value:
                value = self.cipher.decrypt(row.encrypted_value)
                if value is not None:
                    return value
        return self.fallback.get(secret_ref)

    def disable(self, secret_ref: str) -> None:
        self.fallback.disable(secret_ref)
