"""Finnhub historical market data provider.

Classes
-------
FinnhubData
    Historical market data provider for the Finnhub API.

Functions
---------
check_auth
    Return a wrapper that requires an authenticated Finnhub client.
"""

from datetime import date
from importlib.resources import files
from typing import Dict, List, Optional

import pandas as pd
from finnhub import Client

from liualgotrader.common import clock
from liualgotrader.common.types import TimeScale
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.finnhub.config import FinnhubConfig


def check_auth(f):
    """Return a wrapper that requires an authenticated Finnhub client.

    The wrapper forwards only positional arguments.

    Parameters
    ----------
    f
        The method to wrap.
    """

    def wrapper(*args):
        """Return the result of the wrapped method.

        Parameters
        ----------
        *args
            The positional arguments, starting with the instance.

        Raises
        ------
        Raise AssertionError if the instance has no Finnhub client.
        """
        if not args[0].finnhub_rest_client:
            raise AssertionError("Must call w/ authenticated Finnhub client")
        return f(*args)

    return wrapper


class FinnhubData(DataAPI):
    """Historical market data provider for the Finnhub API.

    Only get_symbols and get_symbol_data are supported.

    Attributes
    ----------
    config: FinnhubConfig
        The connection settings.
    finnhub_rest_client
        The Finnhub REST client.
    stock_exchanges: pd.DataFrame
        The supported stock exchanges.

    Methods
    -------
    get_symbols
        Return the stock symbols listed on an exchange.
    get_symbol_data
        Return historical candles for a symbol.
    get_symbols_data
        Raise NotImplementedError.
    get_last_trading
        Raise NotImplementedError.
    get_trading_day
        Raise NotImplementedError.
    get_market_snapshot
        Raise NotImplementedError.
    trading_days_slice
        Raise NotImplementedError.
    num_trading_minutes
        Raise NotImplementedError.
    num_trading_days
        Raise NotImplementedError.
    get_max_data_points_per_load
        Raise NotImplementedError.
    """

    def __init__(self, config: FinnhubConfig):
        """Initialize the Finnhub client and load the stock exchange list.

        Parameters
        ----------
        config: FinnhubConfig
            The connection settings.

        Raises
        ------
        Raise AssertionError if the client cannot be created.
        """
        self.config = config
        self.finnhub_rest_client = Client(api_key=config.api_key)
        if not self.finnhub_rest_client:
            raise AssertionError("Failed to authenticate Finnhub  client")

        with (
            files("liualgotrader")
            .joinpath("res", "finnhub_exchanges.csv")
            .open() as f
        ):
            self.stock_exchanges: pd.DataFrame = pd.read_csv(f)

    @check_auth
    def get_symbols(
        self,
        country: str = "US",
    ) -> List[Dict]:
        """Return the stock symbols listed on an exchange.

        Parameters
        ----------
        country: str, default "US"
            The Finnhub exchange code.

        Returns
        -------
        Return the symbol records reported by Finnhub.

        Raises
        ------
        Raise AssertionError if country is not a supported exchange code or the
        client is not set.
        """
        if country not in self.stock_exchanges.code.to_list():
            raise AssertionError(
                f"country code {country} not supported, valid values are {self.stock_exchanges.code.to_list()}"
            )
        return self.finnhub_rest_client.stock_symbols(exchange=country)

    # @check_auth
    def get_symbol_data(
        self,
        symbol: str,
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> pd.DataFrame:
        """Return historical candles for a symbol.

        Parameters
        ----------
        symbol: str
            The symbol to load.
        start: date
            The first date to load.
        end: Optional[date], default None
            The last date to load, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            TimeScale.minute or TimeScale.day.

        Returns
        -------
        Return a DataFrame indexed by New York time with the open, high, low,
        close and volume columns; a daily candle is indexed by midnight of its
        date.

        Raises
        ------
        Raise AssertionError for any other scale and ValueError if no data is
        available.
        """
        end = end or clock.today()
        _start = int(pd.Timestamp(start, tz=clock.NY).timestamp())
        _end = int(
            pd.Timestamp(
                end if scale == TimeScale.day else end + pd.Timedelta(days=1),
                tz=clock.NY,
            ).timestamp()
        )
        t: Optional[str] = (
            "1"
            if scale == TimeScale.minute
            else "D" if scale == TimeScale.day else None
        )

        if not t:
            raise AssertionError(
                f"timescale {scale} not support in Finnhub implementation"
            )
        data = pd.DataFrame(
            self.finnhub_rest_client.stock_candles(
                symbol,
                t,
                _start,
                _end,
            )
        )
        times = pd.to_datetime(data.t, unit="s", utc=True)
        data = data.set_index(
            # Finnhub stamps a daily candle with midnight UTC of its date
            times.dt.tz_localize(None).dt.tz_localize(clock.NY)
            if scale == TimeScale.day
            else times.dt.tz_convert(clock.NY)
        )
        data = data[data.s == "ok"]
        data = data.drop(columns=["s", "t"])
        data.rename(
            columns={
                "o": "open",
                "c": "close",
                "h": "high",
                "l": "low",
                "v": "volume",
            },
            inplace=True,
        )

        if data.empty:
            raise ValueError(
                f"[ERROR] {symbol} has no data for {_start} to {_end} w {scale.name}"
            )

        return data

    def get_symbols_data(
        self,
        symbols: List[str],
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> Dict[str, pd.DataFrame]:
        """Raise NotImplementedError, as bulk loading is not supported.

        Parameters
        ----------
        symbols: List[str]
            The symbols to load.
        start: date
            The start of the date range.
        end: Optional[date], default None
            The end of the date range, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            The bar resolution.
        """
        raise NotImplementedError("get_symbols_data")

    def get_last_trading(self, symbol: str) -> pd.Timestamp:
        """Raise NotImplementedError, as this lookup is not supported.

        Parameters
        ----------
        symbol: str
            The symbol to look up.
        """
        raise NotImplementedError("get_last_trading")

    def get_trading_day(
        self, symbol: str, now: pd.Timestamp, offset: int
    ) -> pd.Timestamp:
        """Raise NotImplementedError, as this method is not supported.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        now: pd.Timestamp
            The reference time.
        offset: int
            The number of trading days to shift by.
        """
        raise NotImplementedError("get_trading_day")

    async def get_market_snapshot(self, filter_func) -> List[Dict]:
        """Raise NotImplementedError, as snapshots are not supported.

        Parameters
        ----------
        filter_func
            A predicate that selects the snapshots to keep.
        """
        raise NotImplementedError

    def trading_days_slice(self, symbol: str, slice) -> slice:
        """Raise NotImplementedError, as this method is not supported.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        slice
            The timestamp slice to adjust.
        """
        raise NotImplementedError("trading_days_slice")

    def num_trading_minutes(self, symbol: str, start: date, end: date) -> int:
        """Raise NotImplementedError, as this count is not supported.

        Parameters
        ----------
        symbol: str
            The symbol whose trading hours apply.
        start: date
            The start of the date range.
        end: date
            The end of the date range.
        """
        raise NotImplementedError("num_trading_minutes")

    def num_trading_days(self, symbol: str, start: date, end: date) -> int:
        """Raise NotImplementedError, as this count is not supported.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        start: date
            The first date of the range.
        end: date
            The last date of the range.
        """
        raise NotImplementedError("num_trading_days")

    def get_max_data_points_per_load(self) -> int:
        """Raise NotImplementedError, as no load limit is defined."""
        raise NotImplementedError("get_max_data_points_per_load")
