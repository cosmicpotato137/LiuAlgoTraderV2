"""Persist and load daily price data.

Classes
-------
StockOhlc
    Daily price and volume data for a symbol, stored in stock_ohlc.
"""

from datetime import date
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy import UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import (Base, CurrentTimestamp, JsonDict,
                                          dialect_insert)
from liualgotrader.db.session import session_scope


class StockOhlc(Base):
    """Daily price and volume data for a symbol, stored in stock_ohlc.

    Attributes
    ----------
    stock_ohlc_id: int
        The record identifier, or None until the record is loaded.
    symbol: str
        The ticker symbol.
    symbol_date: date
        The trading date; unique per symbol.
    open: float
        The opening price.
    high: float
        The high price.
    low: float
        The low price.
    close: float
        The closing price.
    volume: int
        The traded volume.
    indicators: Optional[Dict[str, Any]]
        The indicators for the date, or None.
    modify_tstamp: Optional[pd.Timestamp]
        The time of the last update, or None.
    create_tstamp: Optional[pd.Timestamp]
        The creation time, set by the database when the record is saved.

    Methods
    -------
    check_stock_date_exists
        Return whether data exists for a date.
    load_by_date
        Load the data of every symbol for a date.
    save
        Save the record, replacing any record for the same date.
    """

    __tablename__ = "stock_ohlc"
    __table_args__ = (UniqueConstraint("symbol", "symbol_date"),)

    stock_ohlc_id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(index=True)
    symbol_date: Mapped[date] = mapped_column(index=True)
    open: Mapped[float]
    high: Mapped[float]
    low: Mapped[float]
    close: Mapped[float]
    volume: Mapped[int]
    indicators: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonDict)
    modify_tstamp: Mapped[Optional[pd.Timestamp]]
    create_tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        server_default=CurrentTimestamp()
    )

    @classmethod
    async def check_stock_date_exists(
        cls, symbol: str, symbol_date: date
    ) -> bool:
        """Return whether daily data exists for a symbol on a date.

        Parameters
        ----------
        symbol: str
            The ticker symbol.
        symbol_date: date
            The trading date.
        """
        async with session_scope() as session:
            return bool(
                await session.scalar(
                    select(
                        select(cls)
                        .where(
                            cls.symbol_date == symbol_date,
                            cls.symbol == symbol,
                        )
                        .exists()
                    )
                )
            )

    @classmethod
    async def load_by_date(cls, symbol_date: date) -> Dict[str, "StockOhlc"]:
        """Load the daily data of every symbol for a date.

        Parameters
        ----------
        symbol_date: date
            The trading date.

        Returns
        -------
        Return a dictionary that maps each symbol to its StockOhlc record.
        """
        async with session_scope() as session:
            records = await session.scalars(
                select(cls).where(cls.symbol_date == symbol_date)
            )
            return {record.symbol: record for record in records}

    async def save(self) -> None:
        """Save this record, replacing any record for its symbol and date."""
        values = dict(
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            indicators=self.indicators,
        )
        async with session_scope() as session:
            await session.execute(
                dialect_insert(session, StockOhlc)
                .values(
                    symbol=self.symbol, symbol_date=self.symbol_date, **values
                )
                .on_conflict_do_update(
                    index_elements=[StockOhlc.symbol, StockOhlc.symbol_date],
                    set_={**values, "modify_tstamp": CurrentTimestamp()},
                )
            )
