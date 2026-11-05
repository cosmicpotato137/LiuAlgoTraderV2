"""Alpaca market calendar of US equities.

Classes
-------
AlpacaCalendar
    Market calendar of US equities from the Alpaca trading API.
"""

from datetime import date
from typing import Iterator, List, Tuple, cast

import pandas as pd
from alpaca.trading.models import Calendar
from alpaca.trading.requests import GetCalendarRequest

from liualgotrader.common import clock
from liualgotrader.market_calendar.base import MarketCalendarAPI
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.alpaca.data import AlpacaData


class AlpacaCalendar(MarketCalendarAPI):
    """Market calendar of US equities from the Alpaca trading API.

    Attributes
    ----------
    data: AlpacaData
        The Alpaca data provider, whose trading client serves the calendar.

    Methods
    -------
    trading_days
        Yield the market hours of each trading day in a date range.
    """

    def __init__(self, config: AlpacaConfig):
        """Initialize the Alpaca clients.

        Parameters
        ----------
        config: AlpacaConfig
            The connection settings.

        Raises
        ------
        Raise the exceptions of AlpacaData.
        """
        self.data = AlpacaData(config)

    def trading_days(
        self, from_date: date, to_date: date
    ) -> Iterator[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Yield the market hours of each trading day in a date range.

        Parameters
        ----------
        from_date: date
            The first day of the range.
        to_date: date
            The last day of the range.
        """
        calendar = cast(
            List[Calendar],
            self.data.trading_client.get_calendar(
                GetCalendarRequest(start=from_date, end=to_date)
            ),
        )
        for day in calendar:
            # Calendar.open and Calendar.close are naive New York times
            yield (
                pd.Timestamp(day.open).tz_localize(clock.NY),
                pd.Timestamp(day.close).tz_localize(clock.NY),
            )
