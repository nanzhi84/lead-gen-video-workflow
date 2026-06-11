from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from queue import Empty, Queue
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import OutboxEvent, utcnow
from packages.core.observability.telemetry import update_outbox_lag
from packages.core.storage.database import OutboxEventRow
from packages.core.storage.repository import Repository


class InProcessFanoutHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Queue]] = {}

    def subscribe(self, run_id: str) -> Queue:
        subscriber: Queue = Queue()
        self._subscribers.setdefault(run_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, run_id: str, subscriber: Queue) -> None:
        subscribers = self._subscribers.get(run_id, [])
        if subscriber in subscribers:
            subscribers.remove(subscriber)
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, payload: dict[str, Any]) -> None:
        for subscriber in list(self._subscribers.get(run_id, [])):
            subscriber.put(payload)

    def get_nowait(self, subscriber: Queue) -> dict[str, Any]:
        return subscriber.get_nowait()


class OutboxDispatcher:
    def __init__(
        self,
        *,
        repository: Repository,
        hub: InProcessFanoutHub,
        poll_interval_seconds: float = 0.2,
        batch_size: int = 100,
    ) -> None:
        self.repository = repository
        self.hub = hub
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        while not self._stopped.is_set():
            await self.dispatch_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()

    async def dispatch_once(self) -> int:
        now = utcnow()
        pending = sorted(
            [
                event
                for event in self.repository.outbox.values()
                if event.status == "pending" and event.available_at <= now
            ],
            key=lambda event: (event.created_at, event.id),
        )[: self.batch_size]
        published = 0
        for event in pending:
            try:
                payload = event.payload if isinstance(event.payload, dict) else {"payload": event.payload}
                run_id = str(payload.get("run_id") or event.aggregate_id)
                self.hub.publish(run_id, payload)
                self.repository.outbox[event.id] = event.model_copy(
                    update={
                        "status": "published",
                        "attempts": event.attempts + 1,
                        "published_at": now,
                        "updated_at": now,
                    }
                )
                published += 1
            except Exception as exc:  # pragma: no cover - exercised through injected hub failures.
                self.repository.outbox[event.id] = self._retry_event(event, exc, now)
        update_outbox_lag(self.repository)
        return published

    @staticmethod
    def _retry_event(event: OutboxEvent, exc: Exception, now: datetime) -> OutboxEvent:
        attempts = event.attempts + 1
        return event.model_copy(
            update={
                "attempts": attempts,
                "available_at": now + timedelta(seconds=min(60, 2**attempts)),
                "last_error": str(exc),
                "updated_at": now,
            }
        )


class SqlAlchemyOutboxDispatcher:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        hub: InProcessFanoutHub,
        poll_interval_seconds: float = 0.2,
        batch_size: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.hub = hub
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        while not self._stopped.is_set():
            await self.dispatch_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()

    async def dispatch_once(self) -> int:
        now = utcnow()
        published = 0
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(OutboxEventRow)
                    .where(OutboxEventRow.status == "pending")
                    .where(OutboxEventRow.available_at <= now)
                    .order_by(OutboxEventRow.created_at, OutboxEventRow.id)
                    .limit(self.batch_size)
                )
            )
            for row in rows:
                try:
                    payload = row.payload if isinstance(row.payload, dict) else {"payload": row.payload}
                    run_id = str(payload.get("run_id") or row.aggregate_id)
                    self.hub.publish(run_id, payload)
                    row.status = "published"
                    row.attempts += 1
                    row.published_at = now
                    row.updated_at = now
                    published += 1
                except Exception as exc:  # pragma: no cover - injected hub failures only.
                    row.attempts += 1
                    row.available_at = now + timedelta(seconds=min(60, 2**row.attempts))
                    row.last_error = str(exc)
                    row.updated_at = now
            _update_sqlalchemy_outbox_lag(session, now)
            session.commit()
        return published


def replay_sqlalchemy_outbox(
    session_factory: sessionmaker[Session],
    *,
    aggregate_type: str,
    aggregate_id: str,
    since_id: str | None = None,
) -> list[dict[str, Any]]:
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(OutboxEventRow)
                .where(OutboxEventRow.aggregate_type == aggregate_type)
                .where(OutboxEventRow.aggregate_id == aggregate_id)
                .order_by(OutboxEventRow.created_at, OutboxEventRow.id)
            )
        )
    if since_id is not None:
        cursor = next(((row.created_at, row.id) for row in rows if row.id == since_id), None)
        if cursor is not None:
            rows = [row for row in rows if (row.created_at, row.id) > cursor]
    return [row.payload for row in rows if isinstance(row.payload, dict)]


def _update_sqlalchemy_outbox_lag(session: Session, now) -> None:
    oldest = session.scalar(
        select(OutboxEventRow.created_at)
        .where(OutboxEventRow.status == "pending")
        .order_by(OutboxEventRow.created_at)
        .limit(1)
    )
    if oldest is None:
        from packages.core.observability.telemetry import OUTBOX_LAG

        OUTBOX_LAG.set(0)
        return
    from packages.core.observability.telemetry import OUTBOX_LAG

    OUTBOX_LAG.set(max(0, (now - oldest).total_seconds()))


@dataclass(frozen=True)
class EventStreamToken:
    token: str
    run_id: str
    expires_at: datetime


class EventStreamTokenStore:
    def __init__(self) -> None:
        self._tokens: dict[str, EventStreamToken] = {}

    def issue(self, run_id: str, ttl: timedelta) -> EventStreamToken:
        token = f"stream_{uuid4().hex[:24]}"
        issued = EventStreamToken(token=token, run_id=run_id, expires_at=utcnow() + ttl)
        self._tokens[token] = issued
        return issued

    def validate(self, token: str, run_id: str) -> bool:
        issued = self._tokens.get(token)
        if issued is None:
            return False
        if issued.run_id != run_id:
            return False
        if issued.expires_at < utcnow():
            self._tokens.pop(token, None)
            return False
        return True


async def receive_from_subscriber(subscriber: Queue, timeout: float = 0.05) -> dict[str, Any] | None:
    try:
        return subscriber.get_nowait()
    except Empty:
        await asyncio.sleep(timeout)
        return None
