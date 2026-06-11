from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.storage.database import create_database_engine, create_session_factory
from packages.core.storage.seed import seed_database


def main() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    session_factory = create_session_factory(create_database_engine())
    with session_factory() as session:
        inserted = seed_database(session)
    print(f"Database bootstrapped; inserted {inserted} seed rows.")


if __name__ == "__main__":
    main()

