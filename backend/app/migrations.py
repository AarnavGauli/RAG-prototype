from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
