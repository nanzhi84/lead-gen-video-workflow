"""In-memory pending-login registry for QR login (publishing center).

Single-host (Mac Mini) runtime state held on ``app.state`` — login flows are short
and host-local; this intentionally does NOT span workers/hosts (run the publishing
host single-worker). Thread-safe (sync API routes run in a threadpool). Entries past
TTL are swept on access; the caller closes the driver session for swept ids.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta

from packages.core.contracts.base import utcnow

DEFAULT_TTL = timedelta(minutes=5)

LoginStatus = str  # "pending" | "active" | "failed"


@dataclass
class LoginSession:
    login_id: str
    account_id: str
    platform: str
    status: LoginStatus
    created_at: object  # datetime; stamped via utcnow()
    detail: str | None = None


class PublishLoginRegistry:
    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self._sessions: dict[str, LoginSession] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def add(self, *, login_id: str, account_id: str, platform: str) -> LoginSession:
        session = LoginSession(
            login_id=login_id,
            account_id=account_id,
            platform=platform,
            status="pending",
            created_at=utcnow(),
        )
        with self._lock:
            self._sessions[login_id] = session
        return session

    def get(self, login_id: str) -> LoginSession | None:
        with self._lock:
            return self._sessions.get(login_id)

    def update(self, login_id: str, *, status: LoginStatus, detail: str | None = None) -> None:
        with self._lock:
            session = self._sessions.get(login_id)
            if session is not None:
                session.status = status
                session.detail = detail

    def remove(self, login_id: str) -> None:
        with self._lock:
            self._sessions.pop(login_id, None)

    def sweep_expired(self) -> list[str]:
        """Remove and return login_ids past TTL (caller closes their driver sessions)."""
        now = utcnow()
        with self._lock:
            expired = [
                login_id
                for login_id, session in self._sessions.items()
                if now - session.created_at > self._ttl
            ]
            for login_id in expired:
                self._sessions.pop(login_id, None)
            return expired
