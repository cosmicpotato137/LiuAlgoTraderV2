"""Declarative base, column types and SQL helpers shared by the models.

The models run on SQLite and PostgreSQL. The types and functions in this
module render the SQL that differs between them.

Classes
-------
Base
    Base class of every model mapped to a database table.
Timestamp
    Date and time column type that behaves the same on SQLite and PostgreSQL.
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
    """Date and time column type that behaves the same on SQLite and PostgreSQL.

    PostgreSQL stores time zone-aware values itself, while SQLite stores the
    date and time as text without a time zone. On SQLite, a time zone-aware
    value is therefore converted to UTC before it is stored, and a column
    with timezone set returns its values as time zone-aware UTC times, as
    PostgreSQL does. Naive values are stored unchanged on both databases.

    Parameters
    ----------
    timezone: bool, default False
        Whether the column holds time zone-aware values.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, timezone: bool = False):
        """Create the column type, as described by the class."""
        super().__init__(timezone=timezone)
        # SQLAlchemy keys its cache of compiled statements by the type and by
        # the attributes named after its __init__ arguments, so this keeps
        # columns with and without time zones from sharing cached SQL.
        self.timezone = timezone

    def process_bind_param(self, value, dialect):
        """Return the value to store in the database for a Python value.

        Parameters
        ----------
        value
            The Python value, usually a datetime or a date, or None.
        dialect
            The dialect of the database.

        Returns
        -------
        Return a time zone-aware datetime as a naive UTC datetime on SQLite,
        and any other value unchanged.
        """
        if (
            dialect.name == "sqlite"
            and isinstance(value, datetime)
            and value.tzinfo is not None
        ):
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        """Return the Python value for a value read from the database.

        Parameters
        ----------
        value
            The value read, a naive datetime on SQLite, or None.
        dialect
            The dialect of the database.

        Returns
        -------
        Return the value as a time zone-aware UTC datetime on SQLite if the
        column has timezone set, and unchanged otherwise.
        """
        if dialect.name == "sqlite" and self.timezone and value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class CurrentTimestamp(FunctionElement):
    """SQL function for the current date and time.

    Use it as a column default, such as server_default=CurrentTimestamp(), or
    as a value in an UPDATE. The value has at least millisecond precision; on
    SQLite it is the UTC time, and on PostgreSQL it is in the session time
    zone.
    """

    type = Timestamp()
    inherit_cache = True


@compiles(CurrentTimestamp)
def _current_timestamp(element, compiler, **kw):
    """Return the SQL of CurrentTimestamp on PostgreSQL.

    Parameters
    ----------
    element: CurrentTimestamp
        The function to compile.
    compiler
        The SQL compiler of the database.
    **kw
        Further compiler options, which are not used.
    """
    return "CURRENT_TIMESTAMP"


@compiles(CurrentTimestamp, "sqlite")
def _sqlite_current_timestamp(element, compiler, **kw):
    """Return the SQL of CurrentTimestamp on SQLite.

    The SQL gives the UTC time to the millisecond, in the text format in
    which SQLAlchemy stores times on SQLite, with six fractional digits, so
    that it sorts and compares correctly with the stored times. SQLite's own
    CURRENT_TIMESTAMP has whole seconds only.

    Parameters
    ----------
    element: CurrentTimestamp
        The function to compile.
    compiler
        The SQL compiler of the database.
    **kw
        Further compiler options, which are not used.
    """
    return "STRFTIME('%Y-%m-%d %H:%M:%f000', 'now')"


class RandomUuid(FunctionElement):
    """SQL function for a random UUID.

    Use it as a column default, such as server_default=RandomUuid(), so that
    rows inserted with plain SQL also get an identifier.
    """

    type = Uuid()
    inherit_cache = True


@compiles(RandomUuid)
def _random_uuid(element, compiler, **kw):
    """Return the SQL of RandomUuid on PostgreSQL 13 or later.

    Parameters
    ----------
    element: RandomUuid
        The function to compile.
    compiler
        The SQL compiler of the database.
    **kw
        Further compiler options, which are not used.
    """
    return "gen_random_uuid()"


@compiles(RandomUuid, "sqlite")
def _sqlite_random_uuid(element, compiler, **kw):
    """Return the SQL of RandomUuid on SQLite.

    The SQL gives 128 random bits as 32 lowercase hexadecimal digits, the
    format in which SQLAlchemy stores a Uuid column on SQLite.

    Parameters
    ----------
    element: RandomUuid
        The function to compile.
    compiler
        The SQL compiler of the database.
    **kw
        Further compiler options, which are not used.
    """
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

    The statement has the on_conflict_do_update and on_conflict_do_nothing
    methods of the dialect-specific inserts of SQLAlchemy, which work the same
    on SQLite and PostgreSQL.

    Parameters
    ----------
    session: AsyncSession
        The session that will run the statement; its database selects the
        dialect.
    model: type
        The model of the table to insert into.

    Returns
    -------
    Return the PostgreSQL insert for a PostgreSQL database, and the SQLite
    insert otherwise.
    """
    if session.get_bind().dialect.name == "postgresql":
        return postgresql.insert(model)
    return sqlite.insert(model)
