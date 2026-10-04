"""Declarative base, column types and SQL helpers shared by the models.

The models run on SQLite and PostgreSQL. The types and functions in this
module render the SQL that differs between them.

Classes
-------
Base
    Base class of every model mapped to a database table.
Timestamp
    Date and time column type that keeps time zones on SQLite.
CurrentTimestamp
    SQL function for the current date and time.
RandomUuid
    SQL function for a random UUID.

Functions
---------
dialect_insert
    Return an INSERT statement that supports ON CONFLICT clauses.
"""

from datetime import datetime, timezone
from typing import Union

from sqlalchemy import JSON, DateTime, Text, TypeDecorator, Uuid
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.functions import FunctionElement

JsonDict = JSON().with_variant(postgresql.JSONB(), "postgresql")
"""Column type for a JSON object, stored as JSONB on PostgreSQL."""

TextList = JSON().with_variant(postgresql.ARRAY(Text), "postgresql")
"""Column type for a list of strings, a text array on PostgreSQL."""


class Timestamp(TypeDecorator):
    """Date and time column type that keeps time zones on SQLite.

    SQLite stores UTC: a time zone-aware value is converted to UTC when
    written, and a column with timezone set returns time zone-aware UTC
    values, as PostgreSQL does.

    Parameters
    ----------
    timezone: bool, default False
        Whether the column holds time zone-aware values.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, timezone: bool = False):
        """Create the column type."""
        super().__init__(timezone=timezone)
        # Part of the statement cache key, because it is an argument.
        self.timezone = timezone

    def process_bind_param(self, value, dialect):
        """Return a value as written to a dialect."""
        if (
            dialect.name == "sqlite"
            and isinstance(value, datetime)
            and value.tzinfo is not None
        ):
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        """Return a value as read from a dialect."""
        if dialect.name == "sqlite" and self.timezone and value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class CurrentTimestamp(FunctionElement):
    """SQL function for the current date and time.

    The value has at least millisecond precision. On SQLite it is the UTC
    time, and on PostgreSQL it is in the session time zone.
    """

    type = Timestamp()
    inherit_cache = True


@compiles(CurrentTimestamp)
def _current_timestamp(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


@compiles(CurrentTimestamp, "sqlite")
def _sqlite_current_timestamp(element, compiler, **kw):
    # SQLite has millisecond precision. Pad it to the six digits that
    # SQLAlchemy writes, so that stored times compare as text.
    return "STRFTIME('%Y-%m-%d %H:%M:%f000', 'now')"


class RandomUuid(FunctionElement):
    """SQL function for a random UUID."""

    type = Uuid()
    inherit_cache = True


@compiles(RandomUuid)
def _random_uuid(element, compiler, **kw):
    return "gen_random_uuid()"


@compiles(RandomUuid, "sqlite")
def _sqlite_random_uuid(element, compiler, **kw):
    return "lower(hex(randomblob(16)))"


class Base(DeclarativeBase):
    """Base class of every model mapped to a database table.

    Attributes annotated as str map to text columns, and as datetime to
    Timestamp columns.
    """

    type_annotation_map = {str: Text(), datetime: Timestamp()}


def dialect_insert(
    session: AsyncSession, model: type
) -> Union[postgresql.Insert, sqlite.Insert]:
    """Return an INSERT statement that supports ON CONFLICT clauses.

    Parameters
    ----------
    session: AsyncSession
        The session that runs the statement, which selects its dialect.
    model: type
        The model of the table to insert into.
    """
    if session.get_bind().dialect.name == "postgresql":
        return postgresql.insert(model)
    return sqlite.insert(model)
