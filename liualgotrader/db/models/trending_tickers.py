"""Persist and load the trending symbols found by scanners.

Classes
-------
TrendingTicker
    Symbol found by a scanner, stored in the trending_tickers table.
"""

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import Base
from liualgotrader.db.session import session_scope


class TrendingTicker(Base):
    """Symbol found by a scanner, stored in the trending_tickers table.

    Attributes
    ----------
    trending_id: int
        The record identifier, or None until the record is saved.
    batch_id: str
        The identifier of the batch the symbol was found in.
    symbol: str
        The trending symbol.
    create_tstamp: Optional[datetime]
        The time the symbol was found, set by the database when saved.
    scanner_name: str
        The name of the scanner that found the symbol.

    Methods
    -------
    save_symbols
        Save the trending symbols of a batch.
    load
        Return the trending symbols of a batch.
    """

    __tablename__ = "trending_tickers"

    trending_id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str]
    symbol: Mapped[str]
    create_tstamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    scanner_name: Mapped[str] = mapped_column(server_default="momentum")

    @classmethod
    async def save_symbols(cls, batch_id: str, symbols: List[str]) -> None:
        """Save the trending symbols of a batch.

        Parameters
        ----------
        batch_id: str
            The batch identifier.
        symbols: List[str]
            The symbols to save.
        """
        async with session_scope() as session:
            session.add_all(
                cls(batch_id=batch_id, symbol=symbol) for symbol in symbols
            )

    @classmethod
    async def load(cls, batch_id: str) -> List[Tuple[str, Optional[datetime]]]:
        """Return the trending symbols of a batch.

        Parameters
        ----------
        batch_id: str
            The batch identifier.

        Returns
        -------
        Return a list of (symbol, creation time) tuples.

        Raises
        ------
        Raise Exception if the batch has no symbols.
        """
        async with session_scope() as session:
            rows = await session.execute(
                select(cls.symbol, cls.create_tstamp).where(
                    cls.batch_id == batch_id
                )
            )
            symbols = [(row[0], row[1]) for row in rows]

        if symbols:
            return symbols
        raise Exception("no data")
