"""Shared base for the SQLAlchemy-backed domain repositories.

Every per-domain SQLAlchemy repository takes a ``sessionmaker`` and opens a
session per operation via ``with self.session_factory() as session:``. This base
owns that single common collaborator so the domain repositories no longer repeat
the identical ``__init__``. It stays deliberately minimal — no query helpers — so
adopting it is behaviour preserving (``self.session_factory`` is the same
attribute the repositories already used).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker


class BaseRepository:
    """Holds the ``sessionmaker`` shared by all SQLAlchemy domain repositories."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
