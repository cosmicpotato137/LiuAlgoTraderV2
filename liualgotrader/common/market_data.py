"""Market data, sector and industry membership, and trading calendar lookups.

Functions
---------
get_symbol_data
    Return a symbol's market data between two dates.
get_sector_tickers
    Return the symbols that belong to a market sector.
get_sectors_tickers
    Return the symbols that belong to any of several sectors.
get_industry_tickers
    Return the symbols that belong to an industry.
get_industries_tickers
    Return the symbols in any of several industries.
get_market_sectors
    Return the distinct, non-empty sector names.
get_market_industries
    Return the distinct, non-empty industry names.
sp500_historical_constituents
    Estimate the S&P 500 constituents as of a date.
get_trading_holidays
    Return the holiday dates of the NYSE calendar.
get_trading_day
    Return the date a number of trading days before a date.
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Set

import numpy as np
import pandas as pd
import pandas_market_calendars
import pytz
import requests
from pandas import DataFrame as df
from sqlalchemy import select

from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.data_loader import m_and_a_data  # type: ignore
from liualgotrader.common.types import TimeScale
from liualgotrader.db.models.ticker_data import TickerData
from liualgotrader.db.session import session_scope
from liualgotrader.fincalcs.vwap import add_daily_vwap

logger = logging.getLogger(__name__)

volume_today: Dict[str, int] = {}
quotes: Dict[str, df] = {}

NY = "America/New_York"
nytz = pytz.timezone(NY)


def get_symbol_data(
    symbol: str,
    start_date: date,
    end_date: date,
    data_loader=None,
    scale="minute",
) -> df:
    """Return a symbol's market data between two dates.

    Parameters
    ----------
    symbol: str
        The symbol to load.
    start_date: date
        The first date of the range.
    end_date: date
        The last date of the range.
    data_loader, default None
        The loader to use, or None to create one.
    scale, default "minute"
        The TimeScale name used when creating a loader.
    """
    if not data_loader:
        data_loader = DataLoader(TimeScale[scale])

    return data_loader[symbol][start_date:end_date]  # type: ignore


async def _select_ticker_column(statement) -> List[str]:
    async with session_scope() as session:
        values = await session.scalars(statement)
        return [value for value in values if value]


async def get_sector_tickers(sector: str) -> List[str]:
    """Return the symbols that belong to the given market sector.

    Omit empty symbols.

    Parameters
    ----------
    sector: str
        The sector name.
    """
    return await _select_ticker_column(
        select(TickerData.symbol).where(TickerData.sector == sector)
    )


async def get_sectors_tickers(sectors: List[str]) -> List[str]:
    """Return the symbols that belong to any of the given market sectors.

    Omit empty symbols.

    Parameters
    ----------
    sectors: List[str]
        The sector names.
    """
    return await _select_ticker_column(
        select(TickerData.symbol).where(TickerData.sector.in_(sectors))
    )


async def get_industry_tickers(industry: str) -> List[str]:
    """Return the symbols that belong to the given industry.

    Omit empty symbols.

    Parameters
    ----------
    industry: str
        The industry name.
    """
    return await _select_ticker_column(
        select(TickerData.symbol).where(TickerData.industry == industry)
    )


async def get_industries_tickers(industries: List[str]) -> List[str]:
    """Return the symbols that belong to any of the given industries.

    Omit empty symbols.

    Parameters
    ----------
    industries: List[str]
        The industry names.
    """
    return await _select_ticker_column(
        select(TickerData.symbol).where(TickerData.industry.in_(industries))
    )


async def get_market_sectors() -> List[str]:
    """Return the distinct, non-empty sector names from the ticker table."""
    return await _select_ticker_column(select(TickerData.sector).distinct())


async def get_market_industries() -> List[str]:
    """Return the distinct, non-empty industry names from the ticker table."""
    return await _select_ticker_column(select(TickerData.industry).distinct())


async def sp500_historical_constituents(date: str):
    """Estimate the S&P 500 constituents as of the given date.

    Download the index history from Wikipedia and undo index changes and
    mergers dated after date. Convert the index of the shared merger and
    acquisition data to datetime in place, and log intermediate results.

    Parameters
    ----------
    date: str
        The date, as a string.

    Returns
    -------
    Return the symbols in no particular order.
    """
    logger.info("loading sp500 constituents for %s", date)
    table = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    )
    symbols: List = table[0].Symbol.to_list()
    changes = table[1]

    changes["date"] = changes.Date.apply(
        lambda x: datetime.strptime(x[0], "%B %d, %Y"), axis=1
    )
    m_and_a_data.index = m_and_a_data.index.astype("datetime64[ns]", copy=True)

    adjusted_symbols = m_and_a_data.loc[date < m_and_a_data.index, "to_symbol"]
    logger.debug("adjusted_symbols %s", adjusted_symbols)
    changes = changes.loc[changes.date > date]

    unadusted: Set = set(symbols)

    logger.debug("changes:%s", changes)
    logger.debug("%s", unadusted)
    while True:
        no_changes = True
        for _, row in changes.iterrows():
            if not row.Added.dropna().empty and row.Added.Ticker in unadusted:
                unadusted.remove(row.Added.Ticker)
                no_changes = False
            if (
                not row.Removed.dropna().empty
                and row.Removed.Ticker in unadusted
            ):
                unadusted.add(row.Removed.Ticker)
                no_changes = False

        if no_changes:
            break

    while True:
        no_changes = True
        for symbol in adjusted_symbols:
            if symbol in unadusted:
                unadusted.add(
                    m_and_a_data.loc[
                        m_and_a_data.to_symbol == symbol, "from_symbol"
                    ].item()
                )
                unadusted.remove(symbol)
                no_changes = False

        if no_changes:
            break

    return list(unadusted)


async def get_trading_holidays() -> List[str]:
    """Return the holiday dates of the New York Stock Exchange calendar."""
    nyse = pandas_market_calendars.get_calendar("NYSE")
    return nyse.holidays().holidays


async def get_trading_day(now: date, offset: int) -> date:
    """Return the date that lies a number of trading days before a date.

    Parameters
    ----------
    now: date
        The reference date.
    offset: int
        The number of NYSE trading days to go back; a negative value goes
        forward.
    """
    cbd_offset = pd.tseries.offsets.CustomBusinessDay(
        n=-offset, holidays=await get_trading_holidays()
    )

    return (now + cbd_offset).date()
