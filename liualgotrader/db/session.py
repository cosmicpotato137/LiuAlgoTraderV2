"""Database connection, transactional sessions and DataFrame queries.

Functions
---------
create_db_connection
    Create the shared database engine.
session_scope
    Open a session whose work is committed as one transaction.
fetch_as_dataframe
    Run a query and return its rows as a DataFrame.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg
import pandas as pd
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from liualgotrader.common import config

logger = logging.getLogger(__name__)

_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _connect(dsn: str) -> async_sessionmaker[AsyncSession]:
    global _session_factory

    # asyncpg parses the DSN itself, so it keeps accepting everything it did
    # before the ORM, such as sslmode or an empty DSN that falls back to the
    # PG* environment variables.
    engine = create_async_engine(
        "postgresql+asyncpg://",
        async_creator=lambda: asyncpg.connect(dsn),
        pool_size=10,
        max_overflow=0,
    )
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("db connection pool initialized w %s", dsn)
    return _session_factory


async def create_db_connection(dsn: Optional[str] = None) -> None:
    """Create the shared database engine, replacing any existing engine.

    Connections are opened on first use, on the running event loop, and log
    the DSN.

    Parameters
    ----------
    dsn: Optional[str], default None
        The database DSN, or None for config.dsn.
    """
    _connect(dsn or config.dsn)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a session whose work is committed as one transaction.

    Create the shared engine for config.dsn if it does not exist. Commit when
    the block exits normally, and roll back if it raises.

    Returns
    -------
    Return an async context manager that yields the session.
    """
    factory = _session_factory or _connect(config.dsn)
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
