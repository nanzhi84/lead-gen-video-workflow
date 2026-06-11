from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from packages.core.contracts import OutboxEvent, utcnow


class InMemoryOutboxStore(Protocol):
    outbox: dict[str, OutboxEvent]


class OutboxWriter:
    def __init__(self, repository: InMemoryOutboxStore) -> None:
        self.repository = repository

    @classmethod
    def in_memory(cls, repository: InMemoryOutboxStore) -> "OutboxWriter":
        return cls(repository)

    def write(
        self,
        *,
        topic: str,
        aggregate_type: str,
        aggregate_id: str,
        payload_schema: str,
        payload,
        dedupe_key: str,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
        event_id: str | None = None,
    ) -> OutboxEvent:
        for event in self.repository.outbox.values():
            if (
                event.aggregate_type == aggregate_type
                and event.aggregate_id == aggregate_id
                and event.topic == topic
                and event.dedupe_key == dedupe_key
            ):
                return event

        now = utcnow()
        event_created_at = created_at or now
        event = OutboxEvent(
            id=event_id or f"evt_{uuid4().hex[:12]}",
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_schema=payload_schema,
            payload=payload,
            dedupe_key=dedupe_key,
            available_at=available_at or event_created_at,
            created_at=event_created_at,
            updated_at=event_created_at,
        )
        self.repository.outbox[event.id] = event
        return event

    def replay(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        since_id: str | None = None,
        include_unpublished: bool = True,
    ) -> list[OutboxEvent]:
        events = [
            event
            for event in self.repository.outbox.values()
            if event.aggregate_type == aggregate_type and event.aggregate_id == aggregate_id
        ]
        if not include_unpublished:
            events = [event for event in events if event.status == "published"]
        ordered = sorted(events, key=lambda event: (event.created_at, event.id))
        if since_id is None:
            return ordered
        return [event for event in ordered if (event.created_at, event.id) > self._cursor(ordered, since_id)]

    @staticmethod
    def _cursor(events: list[OutboxEvent], event_id: str) -> tuple[datetime, str]:
        for event in events:
            if event.id == event_id:
                return event.created_at, event.id
        return datetime.min.replace(tzinfo=utcnow().tzinfo), event_id
