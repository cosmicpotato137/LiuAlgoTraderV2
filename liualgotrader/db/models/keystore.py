"""Persist string values under unique keys in the database.

Classes
-------
KeyStore
    Persistent key-value store, one key per row of the keystore table.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import (Base, CurrentTimestamp, Timestamp,
                                          dialect_insert)
from liualgotrader.db.session import session_scope


class KeyStore(Base):
    """Persistent key-value store, one key per row of the keystore table.

    Attributes
    ----------
    key: str
        The key.
    value: str
        The stored value.
    tstamp: Optional[datetime]
        The time the key was first stored, set by the database.

    Methods
    -------
    load
        Return the value stored under a key.
    save
        Store a value under a key.
    """

    __tablename__ = "keystore"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]
    tstamp: Mapped[Optional[datetime]] = mapped_column(
        Timestamp(timezone=True), server_default=CurrentTimestamp()
    )

    @classmethod
    async def load(cls, key: str) -> Optional[str]:
        """Return the value stored under a key, or None if there is none.

        Parameters
        ----------
        key: str
            The key to look up.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(cls.value).where(cls.key == key)
            )

    @classmethod
    async def save(cls, key: str, value: str) -> None:
        """Store a value under a key, replacing any existing value.

        Parameters
        ----------
        key: str
            The key to store under.
        value: str
            The value to store.
        """
        async with session_scope() as session:
            await session.execute(
                dialect_insert(session, cls)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=[cls.key], set_={"value": value}
                )
            )
