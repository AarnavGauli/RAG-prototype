from __future__ import annotations

from alembic import context
from app import models  # noqa: F401  (register tables)
from app.config import Settings
from app.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured.replace("%%", "%")
    settings = Settings()
    settings.ensure_dirs()
    return settings.database_url or ""


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
