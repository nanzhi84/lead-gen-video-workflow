"""SqlAlchemy persistence for the publishing-center account foundation.

Covers clients, publish-account binding anchors, and case→account publish targets.
Platform login/session state is owned by 小V猫 and is never persisted here.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import CasePublishTarget, Client, PublishAccount
from packages.core.contracts.base import utcnow
from packages.core.storage.database import (
    CasePublishTargetRow,
    ClientRow,
    PublishAccountRow,
)
from packages.core.storage.repository import Repository, new_id
from packages.publishing.accounts_mappers import (
    case_publish_target_row_to_contract,
    client_row_to_contract,
    publish_account_row_to_contract,
)


class SqlAlchemyAccountsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    # --- clients ---
    def list_clients(self, *, include_archived: bool = False, limit: int = 50) -> list[Client]:
        with self.session_factory() as session:
            stmt = select(ClientRow).order_by(ClientRow.created_at.desc()).limit(limit)
            if not include_archived:
                stmt = stmt.where(ClientRow.status == "active")
            return [client_row_to_contract(row) for row in session.scalars(stmt)]

    def get_client(self, client_id: str) -> Client | None:
        with self.session_factory() as session:
            row = session.get(ClientRow, client_id)
            return client_row_to_contract(row) if row is not None else None

    def client_exists(self, client_id: str) -> bool:
        with self.session_factory() as session:
            return session.get(ClientRow, client_id) is not None

    def create_client(self, *, name: str, remark: str = "") -> Client:
        with self.session_factory() as session:
            row = ClientRow(id=new_id("client"), name=name, remark=remark, status="active")
            session.add(row)
            session.commit()
            session.refresh(row)
            return client_row_to_contract(row)

    def patch_client(
        self,
        client_id: str,
        *,
        name: str | None = None,
        remark: str | None = None,
        status: str | None = None,
    ) -> Client | None:
        with self.session_factory() as session:
            row = session.get(ClientRow, client_id)
            if row is None:
                return None
            if name is not None:
                row.name = name
            if remark is not None:
                row.remark = remark
            if status is not None:
                row.status = status
            session.commit()
            session.refresh(row)
            return client_row_to_contract(row)

    # --- accounts ---
    def list_accounts(
        self,
        *,
        client_id: str | None = None,
        platform: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[PublishAccount]:
        with self.session_factory() as session:
            stmt = select(PublishAccountRow).order_by(PublishAccountRow.created_at.desc()).limit(limit)
            if client_id is not None:
                stmt = stmt.where(PublishAccountRow.client_id == client_id)
            if platform is not None:
                stmt = stmt.where(PublishAccountRow.platform == platform)
            if not include_archived:
                stmt = stmt.where(PublishAccountRow.status == "active")
            return [publish_account_row_to_contract(row) for row in session.scalars(stmt)]

    def get_account(self, account_id: str) -> PublishAccount | None:
        with self.session_factory() as session:
            row = session.get(PublishAccountRow, account_id)
            return publish_account_row_to_contract(row) if row is not None else None

    def find_account_by_natural_key(
        self, *, client_id: str, platform: str, account_name: str
    ) -> PublishAccount | None:
        with self.session_factory() as session:
            stmt = select(PublishAccountRow).where(
                PublishAccountRow.client_id == client_id,
                PublishAccountRow.platform == platform,
                PublishAccountRow.account_name == account_name,
            )
            row = session.scalars(stmt).first()
            return publish_account_row_to_contract(row) if row is not None else None

    def create_account(
        self,
        *,
        client_id: str,
        platform: str,
        account_name: str,
        platform_uid: str | None = None,
        xiaovmao_uid: str | None = None,
    ) -> PublishAccount:
        with self.session_factory() as session:
            row = PublishAccountRow(
                id=new_id("pubacct"),
                client_id=client_id,
                platform=platform,
                account_name=account_name,
                platform_uid=platform_uid,
                xiaovmao_uid=xiaovmao_uid,
                status="active",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return publish_account_row_to_contract(row)

    def patch_account(
        self,
        account_id: str,
        *,
        account_name: str | None = None,
        platform_uid: str | None = None,
        platform_uid_set: bool = False,
        xiaovmao_uid: str | None = None,
        xiaovmao_uid_set: bool = False,
        status: str | None = None,
    ) -> PublishAccount | None:
        with self.session_factory() as session:
            row = session.get(PublishAccountRow, account_id)
            if row is None:
                return None
            if account_name is not None:
                row.account_name = account_name
            if platform_uid_set:
                row.platform_uid = platform_uid
            if xiaovmao_uid_set:
                row.xiaovmao_uid = xiaovmao_uid
            if status is not None:
                row.status = status
            session.commit()
            session.refresh(row)
            return publish_account_row_to_contract(row)

    def accounts_client_map(self, account_ids: list[str]) -> dict[str, str]:
        """Return ``{account_id: client_id}`` for the given accounts (same-client check)."""
        if not account_ids:
            return {}
        with self.session_factory() as session:
            stmt = select(PublishAccountRow.id, PublishAccountRow.client_id).where(
                PublishAccountRow.id.in_(account_ids),
                PublishAccountRow.status == "active",
            )
            return {account_id: client_id for account_id, client_id in session.execute(stmt)}

    # --- targets ---
    def list_targets(self, case_id: str) -> list[CasePublishTarget]:
        with self.session_factory() as session:
            return self._targets_for_case(session, case_id)

    def set_targets(self, case_id: str, account_ids: list[str]) -> list[CasePublishTarget]:
        """Idempotently replace the full target set for a case."""
        wanted = list(dict.fromkeys(account_ids))  # de-dupe, preserve order
        with self.session_factory() as session:
            existing = {
                row.account_id: row
                for row in session.scalars(
                    select(CasePublishTargetRow).where(CasePublishTargetRow.case_id == case_id)
                )
            }
            for account_id, row in existing.items():
                if account_id not in wanted:
                    session.delete(row)
            for account_id in wanted:
                if account_id not in existing:
                    session.add(
                        CasePublishTargetRow(
                            id=new_id("target"), case_id=case_id, account_id=account_id, enabled=True
                        )
                    )
            session.commit()
            return self._targets_for_case(session, case_id)

    def delete_targets_for_account(self, account_id: str) -> None:
        with self.session_factory() as session:
            session.execute(
                delete(CasePublishTargetRow).where(CasePublishTargetRow.account_id == account_id)
            )
            session.commit()

    def _targets_for_case(self, session: Session, case_id: str) -> list[CasePublishTarget]:
        rows = session.scalars(
            select(CasePublishTargetRow)
            .where(CasePublishTargetRow.case_id == case_id)
            .order_by(CasePublishTargetRow.created_at.asc())
        )
        out: list[CasePublishTarget] = []
        for row in rows:
            account = session.get(PublishAccountRow, row.account_id)
            out.append(case_publish_target_row_to_contract(row, account))
        return out


class MemoryAccountsRepository:
    """In-memory mirror of :class:`SqlAlchemyAccountsRepository` over the runtime
    ``Repository`` dicts, so the account API works on the memory backend (tests)."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    # --- clients ---
    def list_clients(self, *, include_archived: bool = False, limit: int = 50) -> list[Client]:
        items = [c for c in self.repo.clients.values() if include_archived or c.status == "active"]
        items.sort(key=lambda c: c.created_at, reverse=True)
        return items[:limit]

    def get_client(self, client_id: str) -> Client | None:
        return self.repo.clients.get(client_id)

    def client_exists(self, client_id: str) -> bool:
        return client_id in self.repo.clients

    def create_client(self, *, name: str, remark: str = "") -> Client:
        client = Client(id=new_id("client"), name=name, remark=remark, status="active")
        self.repo.clients[client.id] = client
        return client

    def patch_client(
        self,
        client_id: str,
        *,
        name: str | None = None,
        remark: str | None = None,
        status: str | None = None,
    ) -> Client | None:
        client = self.repo.clients.get(client_id)
        if client is None:
            return None
        updates: dict = {"updated_at": utcnow()}
        if name is not None:
            updates["name"] = name
        if remark is not None:
            updates["remark"] = remark
        if status is not None:
            updates["status"] = status
        updated = client.model_copy(update=updates)
        self.repo.clients[client_id] = updated
        return updated

    # --- accounts ---
    def list_accounts(
        self,
        *,
        client_id: str | None = None,
        platform: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[PublishAccount]:
        items = list(self.repo.publish_accounts.values())
        if client_id is not None:
            items = [a for a in items if a.client_id == client_id]
        if platform is not None:
            items = [a for a in items if a.platform == platform]
        if not include_archived:
            items = [a for a in items if a.status == "active"]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return items[:limit]

    def get_account(self, account_id: str) -> PublishAccount | None:
        return self.repo.publish_accounts.get(account_id)

    def find_account_by_natural_key(
        self, *, client_id: str, platform: str, account_name: str
    ) -> PublishAccount | None:
        for account in self.repo.publish_accounts.values():
            if (
                account.client_id == client_id
                and account.platform == platform
                and account.account_name == account_name
            ):
                return account
        return None

    def create_account(
        self,
        *,
        client_id: str,
        platform: str,
        account_name: str,
        platform_uid: str | None = None,
        xiaovmao_uid: str | None = None,
    ) -> PublishAccount:
        account = PublishAccount(
            id=new_id("pubacct"),
            client_id=client_id,
            platform=platform,
            account_name=account_name,
            platform_uid=platform_uid,
            xiaovmao_uid=xiaovmao_uid,
            login_state="unknown",
            status="active",
        )
        self.repo.publish_accounts[account.id] = account
        return account

    def patch_account(
        self,
        account_id: str,
        *,
        account_name: str | None = None,
        platform_uid: str | None = None,
        platform_uid_set: bool = False,
        xiaovmao_uid: str | None = None,
        xiaovmao_uid_set: bool = False,
        status: str | None = None,
    ) -> PublishAccount | None:
        account = self.repo.publish_accounts.get(account_id)
        if account is None:
            return None
        updates: dict = {"updated_at": utcnow()}
        if account_name is not None:
            updates["account_name"] = account_name
        if platform_uid_set:
            updates["platform_uid"] = platform_uid
        if xiaovmao_uid_set:
            updates["xiaovmao_uid"] = xiaovmao_uid
        if status is not None:
            updates["status"] = status
        updated = account.model_copy(update=updates)
        self.repo.publish_accounts[account_id] = updated
        return updated

    def accounts_client_map(self, account_ids: list[str]) -> dict[str, str]:
        return {
            account_id: self.repo.publish_accounts[account_id].client_id
            for account_id in account_ids
            if account_id in self.repo.publish_accounts
            and self.repo.publish_accounts[account_id].status == "active"
        }

    # --- targets ---
    def list_targets(self, case_id: str) -> list[CasePublishTarget]:
        items = [t for t in self.repo.case_publish_targets.values() if t.case_id == case_id]
        items.sort(key=lambda t: t.created_at)
        return [self._hydrate(t) for t in items]

    def set_targets(self, case_id: str, account_ids: list[str]) -> list[CasePublishTarget]:
        wanted = list(dict.fromkeys(account_ids))
        for target_id, target in list(self.repo.case_publish_targets.items()):
            if target.case_id == case_id and target.account_id not in wanted:
                del self.repo.case_publish_targets[target_id]
        present = {
            t.account_id for t in self.repo.case_publish_targets.values() if t.case_id == case_id
        }
        for account_id in wanted:
            if account_id not in present:
                target = CasePublishTarget(
                    id=new_id("target"), case_id=case_id, account_id=account_id, enabled=True
                )
                self.repo.case_publish_targets[target.id] = target
        return self.list_targets(case_id)

    def delete_targets_for_account(self, account_id: str) -> None:
        for target_id, target in list(self.repo.case_publish_targets.items()):
            if target.account_id == account_id:
                del self.repo.case_publish_targets[target_id]

    def _hydrate(self, target: CasePublishTarget) -> CasePublishTarget:
        account = self.repo.publish_accounts.get(target.account_id)
        if account is None:
            return target
        return target.model_copy(
            update={
                "platform": account.platform,
                "account_name": account.account_name,
                "client_id": account.client_id,
            }
        )
