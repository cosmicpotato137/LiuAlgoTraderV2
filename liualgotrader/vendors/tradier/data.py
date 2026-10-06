"""Tradier historical market data provider.

Classes
-------
TradierData
    Market data provider for the Tradier brokerage REST API.
"""

import logging
import time as time_action
from datetime import date, time
from typing import Callable, Dict, List, Optional

import pandas as pd
import pandas_market_calendars
import requests

from liualgotrader.common import clock
from liualgotrader.common.types import TimeScale
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.tradier.config import TradierConfig

logger = logging.getLogger(__name__)


class TradierData(DataAPI):
    """DataAPI implementation backed by the Tradier brokerage REST API.

    Snapshots, symbol listing and several trading-calendar methods are not
    supported.

    Attributes
    ----------
    config: TradierConfig
        The connection settings.

    Methods
    -------
    get_symbol_data
        Return daily or minute bars for a symbol.
    get_market_snapshot
        Raise NotImplementedError.
    get_symbols
        Raise NotImplementedError.
    get_symbols_data
        Return None.
    get_last_trading
        Return the most recent time the market was open.
    get_trading_day
        Shift a time by NYSE business days.
    trading_days_slice
        Raise NotImplementedError.
    num_trading_minutes
        Raise NotImplementedError.
    num_trading_days
        Raise NotImplementedError.
    get_max_data_points_per_load
        Raise NotImplementedError.
    """

    datapoints_per_request = 500
    max_trades_per_minute = 10

    def __init__(self, config: TradierConfig):
        """Initialize the data provider.

        Parameters
        ----------
        config: TradierConfig
            The connection settings.
        """
        self.config = config

    def _get(self, url: str, params: Dict = None):
        """Return the response to an authenticated Tradier GET request.

        Retry without limit, pausing between attempts, while the server
        responds with status 429 or 502.

        Parameters
        ----------
        url: str
            The URL to request.
        params: Dict, default None
            The query parameters, or None for none.
        """
        if params is None:
            params = {}
        r = requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
            },
        )
        if r.status_code in (429, 502):
            logger.warning(
                "%s return %s, waiting and re-trying", url, r.status_code
            )
            time_action.sleep(10)
            return self._get(url, params)

        return r

    def get_symbol_data(
        self,
        symbol: str,
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> pd.DataFrame:
        """Return historical daily or minute bars for a symbol.

        Parameters
        ----------
        symbol: str
            The ticker.
        start: date
            The first date to load.
        end: Optional[date], default None
            The last date to load, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            TimeScale.day or TimeScale.minute.

        Returns
        -------
        Return a DataFrame of bars indexed by New York time, with daily bars at
        midnight and minute bars limited to 04:00 through 19:59; it is empty
        if no minute data exists.

        Raises
        ------
        Raise NotImplementedError for any other scale, and ValueError on an
        HTTP error status or malformed minute data.
        """
        end = end or clock.today()
        if scale == TimeScale.day:
            url = f"{self.config.base_url}markets/history"
            interval = "daily"
            s = str(start)
            e = str(end)
        elif scale == TimeScale.minute:
            # Tradier reads the times of a request in New York time
            url = f"{self.config.base_url}markets/timesales"
            interval = "1min"
            s = f"{start} 00:00"
            e = f"{end} 23:59"
        else:
            raise NotImplementedError(f"scale {scale} not implemented yet")

        response = self._get(
            url,
            params={
                "symbol": symbol,
                "interval": interval,
                "start": s,
                "end": e,
            },
        )

        if response.status_code != 200:
            raise ValueError(
                f"HTTP ERROR {response.status_code} {response.text}"
            )

        df: pd.DataFrame = pd.DataFrame()
        if scale == TimeScale.day:
            data = response.json()["history"]["day"]
            df = pd.DataFrame(data=data)

            df.date = pd.to_datetime(df.date).dt.tz_localize(clock.NY)
            df.set_index(
                "date", drop=True, inplace=True, verify_integrity=True
            )
            df["count"] = 0
            df["average"] = 0.0
            df["vwap"] = 0.0
        elif scale == TimeScale.minute:
            data = response.json()

            try:
                if data and data["series"]:
                    data = data["series"]["data"]
                    df = pd.DataFrame.from_records(data)
                    df.time = pd.to_datetime(
                        df.timestamp, unit="s", utc=True
                    ).dt.tz_convert(clock.NY)
                    df.set_index(
                        "time", drop=True, inplace=True, verify_integrity=True
                    )
                    df.drop(["timestamp"], axis=1, inplace=True)
                    df["count"] = 0
                    df = df.rename(columns={"price": "average"}).between_time(
                        "04:00", "19:59"
                    )
            except Exception as exc:
                raise ValueError(f"data={data}") from exc

        return df

    async def get_market_snapshot(
        self, filter_func: Optional[Callable]
    ) -> List[Dict]:
        """Raise NotImplementedError, as market snapshots are unsupported.

        Parameters
        ----------
        filter_func: Optional[Callable]
            A predicate that selects snapshots, or None.
        """
        raise NotImplementedError("get_market_snapshot")

    def get_symbols(self) -> List[str]:
        """Raise NotImplementedError, as listing symbols is unsupported."""
        raise NotImplementedError("get_symbols")

    def get_symbols_data(
        self,
        symbols: List[str],
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> Dict[str, pd.DataFrame]:
        """Return None, as loading several symbols at once is unimplemented.

        Parameters
        ----------
        symbols: List[str]
            The symbols to load.
        start: date
            The first date to load.
        end: Optional[date], default None
            The last date to load, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            The bar size.
        """
        ...

    def _get_previous_month_last_trading(
        self, month: int, year: int
    ) -> pd.Timestamp:
        """Return the latest trading time before a month's last listed day.

        Request the calendars of earlier months if needed.

        Parameters
        ----------
        month: int
            The month whose Tradier calendar is searched.
        year: int
            The year of the month.

        Returns
        -------
        Return 20:00 New York time on that day.
        """
        url = f"{self.config.base_url}markets/calendar"
        response = self._get(url, params={"month": month})
        data = response.json()
        return self._get_previous_last_trading(
            data, len(data["calendar"]["days"]["day"]) - 1, month, year
        )

    def _get_previous_last_trading(
        self, data: Dict, index: int, month: int, year: int
    ) -> pd.Timestamp:
        """Return the latest trading time before a day in a monthly calendar.

        Request the calendars of earlier months if needed.

        Parameters
        ----------
        data: Dict
            The Tradier calendar response for the month.
        index: int
            The position of the day in the calendar.
        month: int
            The calendar month.
        year: int
            The calendar year.

        Returns
        -------
        Return 20:00 New York time on the latest earlier open day.
        """
        if index > 0:
            if data["calendar"]["days"]["day"][index - 1]["status"] == "open":
                day = date.fromisoformat(
                    data["calendar"]["days"]["day"][index - 1]["date"]
                )
                return pd.Timestamp.combine(day, time(hour=20)).tz_localize(
                    clock.NY
                )
            return self._get_previous_last_trading(
                data, index - 1, month, year
            )
        return (
            self._get_previous_month_last_trading(month=month - 1, year=year)
            if month > 0
            else self._get_previous_month_last_trading(month=12, year=year - 1)
        )

    def get_last_trading(self, symbol: str) -> pd.Timestamp:
        """Return the most recent time at which the market was open.

        Parameters
        ----------
        symbol: str
            Ignored.

        Returns
        -------
        Return the current New York time if today is a trading day, and
        otherwise 20:00 New York time on the latest earlier trading day.

        Raises
        ------
        Raise AssertionError if today is missing from the Tradier calendar.
        """
        url = f"{self.config.base_url}markets/calendar"
        response = self._get(
            url,
        )
        data = response.json()
        now = clock.now()
        today = now.date()
        for i, day in enumerate(data["calendar"]["days"]["day"]):
            if day["date"] == str(today):
                if day["status"] == "open":
                    return now

                return self._get_previous_last_trading(
                    data, i, today.month, today.year
                )
            i += 1

        raise AssertionError(
            f"Could not find {today} in current trading month"
        )

    def _get_trading_holidays(self) -> List[str]:
        """Return the NYSE holidays from pandas_market_calendars."""
        nyse = pandas_market_calendars.get_calendar("NYSE")
        return nyse.holidays().holidays

    def get_trading_day(
        self, symbol: str, now: pd.Timestamp, offset: int
    ) -> pd.Timestamp:
        """Return now shifted by offset NYSE business days.

        Parameters
        ----------
        symbol: str
            Ignored.
        now: pd.Timestamp
            The reference time.
        offset: int
            The number of business days to add.
        """
        cbd_offset = pd.tseries.offsets.CustomBusinessDay(
            n=offset, holidays=self._get_trading_holidays()
        )

        return now + cbd_offset

    def trading_days_slice(self, symbol: str, time_slice) -> slice:
        """Raise NotImplementedError, as slicing by days is unsupported.

        Parameters
        ----------
        symbol: str
            The symbol.
        time_slice
            The timestamp slice.
        """
        raise NotImplementedError("trading_days_slice")

    def num_trading_minutes(self, symbol: str, start: date, end: date) -> int:
        """Raise NotImplementedError, as counting minutes is unsupported.

        Parameters
        ----------
        symbol: str
            The symbol.
        start: date
            The first date.
        end: date
            The last date.
        """
        raise NotImplementedError("num_trading_minutes")

    def num_trading_days(self, symbol: str, start: date, end: date) -> int:
        """Raise NotImplementedError, as counting days is unsupported.

        Parameters
        ----------
        symbol: str
            The symbol.
        start: date
            The first date.
        end: date
            The last date.
        """
        raise NotImplementedError("num_trading_days")

    def get_max_data_points_per_load(self) -> int:
        """Raise NotImplementedError, as no load limit is defined."""
        raise NotImplementedError("get_max_data_points_per_load")
