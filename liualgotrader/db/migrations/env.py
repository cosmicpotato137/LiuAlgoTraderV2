"""Alembic environment: run the migrations on a database.

Alembic runs this module for every command. When the framework upgrades a
database, liualgotrader.db.session passes its own connection in
config.attributes["connection"], and the migrations run in the transaction of
that connection. When a developer runs the alembic command, configured by the
alembic.ini of the repository, it connects to the database of the DSN
environment variable, or to the default SQLite database; with --sql, it
prints the SQL instead of running it.

Functions
---------
_render_item
    Write the Python code of a column type or default in a new migration.
_run_migrations
    Run the alembic command on a connection.
_run_migrations_on_dsn
    Run the alembic command on the database of the DSN.
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
    """Write the Python code of a column type or default in a new migration.

    `alembic revision --autogenerate` writes each new column of a migration as
    Python code. Left to itself, it would write

    - Timestamp type as liualgotrader.db.models.base.Timestamp(...),
      without importing that module;
    - CurrentTimestamp or RandomUuid as the SQL of the database
      that it compares the models with, such as SQLite's STRFTIME(...),
      which fails on PostgreSQL;
    - a false() or true() default as SQLite's 0 or 1, which PostgreSQL
      rejects for a boolean column.

    This function writes them as Timestamp(...), CurrentTimestamp(),
    RandomUuid(), sa.false() and sa.true(), with the imports they need, so
    that the migration works on both databases.

    Parameters
    ----------
    type_: str
        The kind of item, such as "type" or "server_default".
    obj
        The item: a column type, or the server default of a column.
    autogen_context: AutogenContext
        The migration being written, which collects the imports it needs.

    Returns
    -------
    Return the Python code of the item, or False to leave it to Alembic.
    """
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
    """Run the alembic command on a connection.

    Upgrade or downgrade the schema, or for `alembic revision --autogenerate`,
    write a migration for the differences between the models and the
    database.

    Parameters
    ----------
    connection: Connection
        The connection to the database.
    """
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_item=_render_item,
        # Write changes to existing SQLite tables as batch operations, which
        # rebuild a table when SQLite cannot alter it in place.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_on_dsn() -> None:
    """Run the alembic command on the database of the DSN.

    Connect to the database that config.dsn names, as the framework does,
    and disconnect when the command is done.
    """
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
