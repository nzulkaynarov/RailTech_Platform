"""Окружение Alembic: async-движок из app.config, метаданные из app.models."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.log import configure_logging
from app.models.base import Base

settings = get_settings()
configure_logging(settings)
target_metadata = Base.metadata


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    # Таблицы Procrastinate и LangGraph управляются их собственными схемами.
    if type_ == "table" and name is not None:
        return not name.startswith(("procrastinate_", "checkpoint"))
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.sqlalchemy_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
