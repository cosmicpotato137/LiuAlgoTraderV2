import pathlib

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import liualgotrader.db
import liualgotrader.db.models  # noqa: F401
from liualgotrader.db.models.base import Base
from liualgotrader.db.models.keystore import KeyStore
from liualgotrader.db.session import (create_db_connection, database_url,
                                      session_scope)


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


def head_revision() -> str:
    migrations = pathlib.Path(liualgotrader.db.__file__).parent / "migrations"
    head = ScriptDirectory(str(migrations)).get_current_head()
    if head is None:
        raise AssertionError("no migrations")
    return head


@pytest.mark.asyncio
async def test_migrations_match_models() -> bool:
    async with session_scope() as session:
        connection = await session.connection()
        differences = await connection.run_sync(
            lambda sync_connection: compare_metadata(
                MigrationContext.configure(sync_connection), Base.metadata
            )
        )
    if differences:
        raise AssertionError(
            f"models differ from the migrations, add a migration: {differences}"
        )

    return True


@pytest.mark.asyncio
async def test_adopts_database_without_migrations(tmp_path) -> bool:
    dsn = f"sqlite:///{tmp_path}/liu.db"
    engine = create_async_engine(database_url(dsn))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    await create_db_connection(dsn)
    await KeyStore.save("k", "v")
    async with session_scope() as session:
        version = await session.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    if version != head_revision() or await KeyStore.load("k") != "v":
        raise AssertionError(f"database not adopted, at version {version}")

    return True
