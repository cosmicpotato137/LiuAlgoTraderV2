"""Abstract interface for market calendars, and the crypto calendar.

Classes
-------
MarketCalendarAPI
    Abstract base class for market calendars.
CryptoCalendar
    Calendar of the crypto market, which trades every day.
"""

from abc import ABCMeta, abstractmethod
from datetime import date, time
from typing import Iterator, Tuple

import pandas as pd

from liualgotrader.common import clock


class MarketCalendarAPI(metaclass=ABCMeta):
    """Abstract base class for market calendars.

    Methods
    -------
    trading_days
        Yield the start and end of each trading day in a date range.
    """

    @abstractmethod
    def trading_days(
        self, from_date: date, to_date: date
    ) -> Iterator[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Yield the start and end of each trading day in a date range.

        Implementations must yield the days in order, as New York times.

        Parameters
        ----------
        from_date: date
            The first day of the range.
        to_date: date
            The last day of the range.
        """
        ...


class CryptoCalendar(MarketCalendarAPI):
    """Calendar of the crypto market, which trades every day.

    Methods
    -------
    trading_days
        Yield the start and end of every calendar day in a date range.
    """

    def trading_days(
        self, from_date: date, to_date: date
    ) -> Iterator[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Yield the start and end of every calendar day in a date range.

        Each day spans the whole calendar day in New York time.

        Parameters
        ----------
        from_date: date
            The first day of the range.
        to_date: date
            The last day of the range.
        """
        for day in pd.date_range(from_date, to_date):
            yield (
                pd.Timestamp(day.date(), tz=clock.NY),
                pd.Timestamp.combine(day.date(), time.max).tz_localize(
                    clock.NY
                ),
            )
