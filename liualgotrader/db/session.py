"""Database connection, transactional sessions and DataFrame queries.

The database is SQLite unless the DSN names a PostgreSQL server.

Functions
---------
database_url
    Return the SQLAlchemy URL of a DSN.
create_db_connection
    Create the shared database engine.
upgrade_schema
    Upgrade the database schema to the latest migration.
session_scope
    Open a session whose work is committed as one transaction.
fetch_as_dataframe
    Run a query and return its rows as a DataFrame.
"""

import logging
import pathlib
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import pandas as pd
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, Select, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)

from liualgotrader.common import config

logger = logging.getLogger(__name__)

# The async driver of each database, for URLs that do not name a driver.
_DRIVERS = {
    "sqlite": "sqlite+aiosqlite",
    "postgresql": "postgresql+asyncpg",
    "postgres": "postgresql+asyncpg",
}
# Advisory lock that PostgreSQL processes hold while upgrading the schema.
_SCHEMA_LOCK = 0x6C69755F736368

_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_schema_upgraded = False


def database_url(dsn: str) -> URL:
    """Return the SQLAlchemy URL of a DSN.

    Parameters
    ----------
    dsn: str
        A database URL, such as sqlite:///path/to/liu.db or
        postgresql://user:password@host/db, or an empty string for the SQLite
        database at config.default_db_path.

    Returns
    -------
    Return the URL with the async driver of its database, unless the DSN
    names a driver.

    Raises
    ------
    Raise sqlalchemy.exc.ArgumentError if dsn is not a URL, or ValueError if
    it is not a SQLite or PostgreSQL URL.
    """
    if not dsn:
        return URL.create("sqlite+aiosqlite", database=config.default_db_path)

    url = make_url(dsn)
    url = url.set(drivername=_DRIVERS.get(url.drivername, url.drivername))
    if url.get_backend_name() not in ("sqlite", "postgresql"):
        raise ValueError(
            f"unsupported database {url.get_backend_name()}: "
            "the DSN must be a SQLite or PostgreSQL URL"
        )
    return url


def _configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        # Leave BEGIN to SQLAlchemy, so that savepoints work.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # Write-ahead logging lets processes read while another one writes.
        # The file keeps the setting. Switching to it fails at once while
        # another process holds a lock, so leave it to a later connection.
        cursor.execute("PRAGMA journal_mode")
        if cursor.fetchone()[0] != "wal":
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def on_begin(connection):
        # Take the write lock up front. Processes then wait for each other, up
        # to the connection timeout, instead of failing when a transaction
        # that has read starts to write.
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _connect(dsn: str) -> async_sessionmaker[AsyncSession]:
    global _session_factory, _schema_upgraded

    url = database_url(dsn)
    options: Dict[str, Any] = {}
    backend = url.get_backend_name()
    if backend == "sqlite":
        if url.database and url.database != ":memory:":
            pathlib.Path(url.database).parent.mkdir(
                parents=True, exist_ok=True
            )
        options["connect_args"] = {"timeout": 30}
    else:
        options.update(pool_size=10, max_overflow=0)

    try:
        if dsn and make_url(dsn).drivername in ("postgresql", "postgres"):
            import asyncpg

            # asyncpg parses the DSN itself, so it accepts everything it did
            # before the ORM, such as sslmode, or a DSN without a host that
            # falls back to the PG* environment variables.
            options["async_creator"] = lambda: asyncpg.connect(dsn)
        engine = create_async_engine(url, **options)
    except ModuleNotFoundError as e:
        if e.name != "asyncpg":
            raise
        raise ModuleNotFoundError(
            "PostgreSQL databases need the asyncpg driver: "
            "pip install 'liualgotrader[postgres]'",
            name=e.name,
        ) from e

    if backend == "sqlite":
        _configure_sqlite(engine)

    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    _schema_upgraded = False
    logger.info(
        "db connection pool initialized w %s",
        url.render_as_string(hide_password=True),
    )
    return _session_factory


async def create_db_connection(dsn: Optional[str] = None) -> None:
    """Create the shared database engine, replacing any existing engine.

    Connections are opened on first use, on the running event loop, and log
    the database URL without its password.

    Parameters
    ----------
    dsn: Optional[str], default None
        The database DSN, as accepted by database_url, or None for
        config.dsn.

    Raises
    ------
    Raise ValueError if the DSN is not a SQLite or PostgreSQL URL, or
    ModuleNotFoundError if the PostgreSQL driver is not installed.
    """
    _connect(dsn or config.dsn)


def _upgrade(connection: Connection) -> None:
    # Make concurrent processes upgrade the schema one at a time. On SQLite,
    # BEGIN IMMEDIATE already does.
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK}
        )
    else:
        # Let a migration copy a table that other tables reference: SQLite
        # then checks foreign keys when the transaction commits.
        connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")

    alembic_config = AlembicConfig()
    alembic_config.set_main_option(
        "script_location", "liualgotrader.db:migrations"
    )
    alembic_config.attributes["connection"] = connection
    command.upgrade(alembic_config, "head")


async def upgrade_schema() -> None:
    """Upgrade the database schema to the latest migration.

    Create the tables of a new database, and bring a database created by the
    former database/schema.sql up to date. Create the shared engine for
    config.dsn if it does not exist.
    """
    global _schema_upgraded

    factory = _session_factory or _connect(config.dsn)
    async with factory() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(_upgrade)
    _schema_upgraded = True


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a session whose work is committed as one transaction.

    Create the shared engine for config.dsn if it does not exist, and
    upgrade the database schema on the first session of an engine. Commit
    when the block exits normally, and roll back if it raises.

    Returns
    -------
    Return an async context manager that yields the session.
    """
    factory = _session_factory or _connect(config.dsn)
    if not _schema_upgraded:
        await upgrade_schema()
    async with factory() as session, session.begin():
        yield session


async def fetch_as_dataframe(statement: Select) -> pd.DataFrame:
    """Run a query and return its rows as a pandas DataFrame.

    Parameters
    ----------
    statement: Select
        The query to run.

    Returns
    -------
    Return a DataFrame with one column for each selected column, or an empty
    DataFrame without columns if there are no rows.
    """
    async with session_scope() as session:
        result = await session.execute(statement)
        columns = list(result.keys())
        rows = result.all()

    return pd.DataFrame(data=rows, columns=columns) if rows else pd.DataFrame()
