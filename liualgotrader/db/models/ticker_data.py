"""Persist and load ticker descriptions and daily price data.

Classes
-------
TickerData
    Descriptive information about a ticker, stored in ticker_data.
StockOhlc
    Daily price and volume data for a symbol, stored in stock_ohlc.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import (Base, CurrentTimestamp, JsonDict,
                                          TextList, dialect_insert)
from liualgotrader.db.session import session_scope

logger = logging.getLogger(__name__)

TOO_MANY_CONNECTIONS = "53300"


class TickerData(Base):
    """Descriptive information about a ticker, stored in ticker_data.

    Attributes
    ----------
    symbol: str
        The ticker symbol.
    name: str
        The ticker name.
    description: str
        The ticker description.
    tags: Optional[List[str]]
        The tags assigned to the ticker, or None.
    similar_tickers: Optional[List[str]]
        The symbols of similar tickers, or None.
    industry: Optional[str]
        The industry, or None.
    sector: Optional[str]
        The sector, or None.
    exchange: Optional[str]
        The exchange the ticker trades on, or None.
    short_ratio: Optional[float]
        The short ratio, or None.
    create_tstamp: Optional[pd.Timestamp]
        The creation time, set by the database when the ticker is saved.
    modify_tstamp: Optional[pd.Timestamp]
        The time of the last update, or None.

    Methods
    -------
    load_symbols
        Return every stored ticker symbol.
    save
        Save the ticker, replacing any ticker with the same symbol.
    """

    __tablename__ = "ticker_data"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str]
    tags: Mapped[Optional[List[str]]] = mapped_column(TextList)
    similar_tickers: Mapped[Optional[List[str]]] = mapped_column(TextList)
    industry: Mapped[Optional[str]] = mapped_column(index=True)
    sector: Mapped[Optional[str]] = mapped_column(index=True)
    exchange: Mapped[Optional[str]]
    short_ratio: Mapped[Optional[float]]
    create_tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        server_default=CurrentTimestamp()
    )
    modify_tstamp: Mapped[Optional[pd.Timestamp]]

    @classmethod
    async def load_symbols(cls) -> List[str]:
        """Return every stored ticker symbol.

        Raises
        ------
        Raise Exception if no tickers are stored.
        """
        async with session_scope() as session:
            symbols = list(await session.scalars(select(cls.symbol)))

        if symbols:
            return symbols
        raise Exception("no data")

    async def save(self) -> bool:
        """Save this ticker, replacing any ticker with the same symbol.

        Returns
        -------
        Return True on success, or False if the database has too many
        connections.
        """
        values = dict(
            name=self.name,
            description=self.description,
            tags=self.tags,
            similar_tickers=self.similar_tickers,
            industry=self.industry,
            sector=self.sector,
            exchange=self.exchange,
        )
        try:
            async with session_scope() as session:
                await session.execute(
                    dialect_insert(session, TickerData)
                    .values(symbol=self.symbol, **values)
                    .on_conflict_do_update(
                        index_elements=[TickerData.symbol],
                        set_={**values, "modify_tstamp": CurrentTimestamp()},
                    )
                )
            return True
        except DBAPIError as e:
            if getattr(e.orig, "sqlstate", None) != TOO_MANY_CONNECTIONS:
                raise
            logger.warning(
                "too many db connections: %s. Failed to write ticker %s, will re-try",
                e,
                self.symbol,
            )

        return False


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
    get_latest_date
        Return the latest date with data for a symbol.
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
    async def get_latest_date(cls, symbol: str) -> Optional[date]:
        """Return the latest date with daily data for a symbol.

        Parameters
        ----------
        symbol: str
            The ticker symbol.

        Returns
        -------
        Return None if the symbol has no data.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(func.max(cls.symbol_date)).where(cls.symbol == symbol)
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
