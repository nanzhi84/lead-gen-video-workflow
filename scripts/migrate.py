from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()

