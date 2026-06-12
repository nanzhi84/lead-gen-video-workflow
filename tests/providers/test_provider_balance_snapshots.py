from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.ai.gateway.sqlalchemy_repository import SqlAlchemyProviderRepository
from packages.core.contracts import Money, ProviderBalanceSnapshot, utcnow
from packages.core.storage.database import ProviderBalanceSnapshotRow


def test_sqlalchemy_provider_balance_snapshot_upserts_and_reads_latest():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ProviderBalanceSnapshotRow.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    repository = SqlAlchemyProviderRepository(session_factory)

    first = ProviderBalanceSnapshot(
        id="pbs_1",
        provider_id="deepseek",
        account_group="deepseek.prod",
        balance=Money(amount=Decimal("1.25"), currency="CNY"),
        status="ok",
        checked_at=utcnow(),
    )
    second = first.model_copy(
        update={
            "id": "pbs_2",
            "balance": Money(amount=Decimal("2.50"), currency="CNY"),
            "status": "error",
            "detail": "temporary failure",
            "checked_at": utcnow(),
        }
    )

    repository.upsert_balance_snapshot(first)
    repository.upsert_balance_snapshot(second)

    snapshots = repository.latest_balance_snapshots(provider_id="deepseek")
    assert len(snapshots) == 1
    assert snapshots[0].id == "pbs_1"
    assert snapshots[0].balance.amount == Decimal("2.500000")
    assert snapshots[0].status == "error"
