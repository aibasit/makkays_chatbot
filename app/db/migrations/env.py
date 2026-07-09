"""Alembic migration environment for the synchronous SQLAlchemy engine."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.availability import models as availability_models  # noqa: F401
from app.db.base import Base
from app.crm import models as crm_models  # noqa: F401
from app.dependencies import get_settings
from app.handoff import models as handoff_models  # noqa: F401
from app.quotes import models as quote_models  # noqa: F401
from app.rag import models as rag_models  # noqa: F401
from app.session import models as session_models  # noqa: F401
from app.turns import models as turns_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().db.supabase_db_url_sync.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations without creating an engine."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
