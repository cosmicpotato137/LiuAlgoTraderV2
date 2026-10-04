"""Alembic environment that migrates the database schema.

The framework runs the migrations on its own connection, which it passes in
config.attributes["connection"]. The alembic command, configured by the
alembic.ini of the repository, connects to the database of the DSN
environment variable instead.
"""

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.elements import False_, True_

import liualgotrader.db.models  # noqa: F401, registers every model
from liualgotrader.common import config
from liualgotrader.db.models.base import (Base, CurrentTimestamp, RandomUuid,
                                          Timestamp)
from liualgotrader.db.session import database_url


def _render_item(type_, obj, autogen_context):
    # Render the types and SQL functions of the models by name, rather than
    # as the SQL of the database that autogenerate compares against.
    if type_ == "type" and isinstance(obj, Timestamp):
        autogen_context.imports.add(
            "from liualgotrader.db.models.base import Timestamp"
        )
        return f"Timestamp(timezone={obj.timezone})"
    if type_ == "server_default":
        default = getattr(obj, "arg", None)
        if isinstance(default, (CurrentTimestamp, RandomUuid)):
            name = type(default).__name__
            autogen_context.imports.add(
                f"from liualgotrader.db.models.base import {name}"
            )
            return f"{name}()"
        if isinstance(default, False_):
            return "sa.false()"
        if isinstance(default, True_):
            return "sa.true()"
    return False


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_item=_render_item,
        # SQLite can make most changes to a table only by copying it.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_on_dsn() -> None:
    engine = create_async_engine(
        database_url(config.dsn), poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=database_url(config.dsn),
        target_metadata=Base.metadata,
        render_item=_render_item,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif (connection := context.config.attributes.get("connection")) is not None:
    _run_migrations(connection)
else:
    asyncio.run(_run_migrations_on_dsn())
