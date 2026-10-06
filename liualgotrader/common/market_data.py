"""Market data and trading calendar lookups.

Functions
---------
get_symbol_data
    Return a symbol's market data between two dates.
sp500_historical_constituents
    Estimate the S&P 500 constituents as of a date.
get_trading_holidays
    Return the holiday dates of the NYSE calendar.
get_trading_day
    Return the date a number of trading days before a date.
"""

import io
import logging
from datetime import date
from typing import Dict, List, Set

import numpy as np
import pandas as pd
import pandas_market_calendars
import requests
from pandas import DataFrame as df

from liualgotrader.common import clock, config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.data_loader import m_and_a_data  # type: ignore
from liualgotrader.common.types import TimeScale
from liualgotrader.fincalcs.vwap import add_daily_vwap

logger = logging.getLogger(__name__)

volume_today: Dict[str, int] = {}
quotes: Dict[str, df] = {}


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

    start = pd.Timestamp(start_date, tz=clock.NY)
    end = pd.Timestamp(end_date, tz=clock.NY)
    return data_loader[symbol][start:end]  # type: ignore


def _read_wikipedia_tables(page: str) -> List[pd.DataFrame]:
    """Return the tables of an English Wikipedia article.

    Parameters
    ----------
    page: str
        The title of the article, as it appears in its URL.

    Raises
    ------
    Raise requests.HTTPError if Wikipedia does not return the article.
    """
    response = requests.get(
        f"https://en.wikipedia.org/wiki/{page}",
        # Wikipedia refuses the default User-Agent of HTTP libraries and asks
        # clients to identify themselves.
        headers={
            "User-Agent": f"liualgotrader/{config.build_label} "
            "(https://github.com/amor71/LiuAlgoTrader)"
        },
        timeout=30,
    )
    response.raise_for_status()
    return pd.read_html(io.StringIO(response.text))


async def sp500_historical_constituents(day: date):
    """Estimate the S&P 500 constituents as of the given date.

    Download the current constituents and the index changes from Wikipedia,
    and undo the index changes and mergers dated after day. Log intermediate
    results.

    Parameters
    ----------
    day: date
        The date of the constituents.

    Returns
    -------
    Return the symbols in no particular order.

    Raises
    ------
    Raise requests.HTTPError if Wikipedia does not return the data.
    """
    logger.info("loading sp500 constituents for %s", day)
    symbols: List = _read_wikipedia_tables("List_of_S%26P_500_companies")[
        0
    ].Symbol.to_list()
    changes = _read_wikipedia_tables("Historical_components_of_the_S%26P_500")[
        0
    ]
    effective = pd.to_datetime(
        changes["Effective Date", "Effective Date"], format="%B %d, %Y"
    ).dt.date

    adjusted_symbols = m_and_a_data.loc[day < m_and_a_data.index, "to_symbol"]
    logger.debug("adjusted_symbols %s", adjusted_symbols)
    later = effective[effective > day].sort_values(ascending=False).index

    constituents: Set = set(symbols)

    logger.debug("changes:%s", changes.loc[later])
    logger.debug("%s", constituents)
    # Undo the changes from the newest to the oldest.
    for added, removed in changes.loc[
        later, [("Added", "Ticker"), ("Removed", "Ticker")]
    ].itertuples(index=False):
        if pd.notna(added):
            constituents.discard(added)
        if pd.notna(removed):
            constituents.add(removed)

    while True:
        no_changes = True
        for symbol in adjusted_symbols:
            if symbol in constituents:
                constituents.add(
                    m_and_a_data.loc[
                        m_and_a_data.to_symbol == symbol, "from_symbol"
                    ].item()
                )
                constituents.remove(symbol)
                no_changes = False

        if no_changes:
            break

    return list(constituents)


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
