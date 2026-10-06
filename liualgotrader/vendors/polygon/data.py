"""Polygon market data provider.

Classes
-------
PolygonData
    Market data provider for the Polygon REST API.
"""

import json
from datetime import date
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from polygon import RESTClient
from polygon.exceptions import AuthError

from liualgotrader.common import clock
from liualgotrader.common.types import TimeScale
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.polygon.config import PolygonConfig


class PolygonData(DataAPI):
    """DataAPI implementation backed by the Polygon REST API.

    Only US equities are covered. Batch loads and trading-calendar methods are
    not supported.

    Attributes
    ----------
    config: PolygonConfig
        The connection settings.
    polygon_rest_client
        The authenticated Polygon REST client.

    Methods
    -------
    get_market_snapshot
        Return snapshots of all equity tickers.
    get_symbols
        Return the active Polygon tickers.
    get_symbol_data
        Return historical bars for a symbol.
    get_symbols_data
        Raise NotImplementedError.
    get_last_trading
        Return the time of a symbol's last trade.
    get_trading_day
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

    def __init__(self, config: PolygonConfig):
        """Create the Polygon REST client.

        Parameters
        ----------
        config: PolygonConfig
            The connection settings.

        Raises
        ------
        Raise AssertionError if the client cannot be created, such as when
        config.api_key is not set.
        """
        self.config = config
        try:
            self.polygon_rest_client = RESTClient(config.api_key)
        except AuthError as e:
            raise AssertionError(
                "Failed to authenticate Polygon restful client"
            ) from e

    async def get_market_snapshot(
        self, filter_func: Optional[Callable]
    ) -> List[Dict]:
        """Return the current snapshots of all equity tickers.

        Require at least a starter Polygon subscription.

        Parameters
        ----------
        filter_func: Optional[Callable]
            A predicate that selects snapshots, or None for all.

        Returns
        -------
        Return each snapshot as the dict sent by Polygon, keyed by the Polygon
        field names such as ticker, day, lastTrade, prevDay and
        todaysChangePerc.

        Raises
        ------
        Raise AssertionError if the REST client is missing.
        """
        if not self.polygon_rest_client:
            raise AssertionError("Must call w/ authenticated polygon client")
        # this API endpoint requires at least starter subscriptions from Polygon
        response = self.polygon_rest_client.get_snapshot_all(
            "stocks", raw=True
        )
        tickers = json.loads(response.data.decode("utf-8")).get("tickers", [])
        return (
            list(filter(filter_func, tickers))
            if filter_func is not None
            else tickers
        )

    def get_symbols(self) -> List[str]:
        """Return the tickers of all active Polygon symbols, in no set order.

        Raises
        ------
        Raise AssertionError if the REST client is missing.
        """
        if not self.polygon_rest_client:
            raise AssertionError("Must call w/ authenticated polygon client")
        # the client iterates over every page of the response
        tickers = self.polygon_rest_client.list_tickers(
            active=True, limit=1000
        )
        # use set to deduplicate in case pages return duplicate symbols
        return list({ticker.ticker for ticker in tickers})

    def get_symbol_data(
        self,
        symbol: str,
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> pd.DataFrame:
        """Return split-adjusted historical bars for a symbol.

        Parameters
        ----------
        symbol: str
            The ticker.
        start: date
            The first date to load.
        end: Optional[date], default None
            The last date to load, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            The bar size.

        Returns
        -------
        Return a DataFrame indexed by New York time with open, high, low,
        close, volume, average, count and vwap columns; average holds the
        Polygon volume-weighted price and vwap is NaN.

        Raises
        ------
        Raise ValueError if no data is returned, or AssertionError if the REST
        client is missing.
        """
        if not self.polygon_rest_client:
            raise AssertionError("Must call w/ authenticated polygon client")

        end = end or clock.today()
        # the client iterates over every page of the response
        aggs = list(
            self.polygon_rest_client.list_aggs(
                symbol, 1, scale.name, start, end, adjusted=True, limit=50000
            )
        )
        if not aggs:
            raise ValueError(
                f"[ERROR] {symbol} has no data for {start} to {end} w {scale.name}"
            )

        d = {
            pd.Timestamp(agg.timestamp, unit="ms", tz="UTC").tz_convert(
                clock.NY
            ): [
                agg.open,
                agg.high,
                agg.low,
                agg.close,
                agg.volume,
                agg.vwap,
                agg.transactions,
            ]
            for agg in aggs
        }
        df = pd.DataFrame.from_dict(
            d,
            orient="index",
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "average",
                "count",
            ],
        )
        # pandas 3 infers millisecond resolution from the timestamps
        df.index = df.index.as_unit("ns")
        df["vwap"] = np.nan
        return df

    def get_symbols_data(
        self,
        symbols: List[str],
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> Dict[str, pd.DataFrame]:
        """Raise NotImplementedError, as batch loading is unsupported.

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
        raise NotImplementedError("get_symbols_data")

    def get_last_trading(self, symbol: str) -> pd.Timestamp:
        """Return the time of the last trade of a symbol.

        Parameters
        ----------
        symbol: str
            The ticker.
        """
        snapshot = self.polygon_rest_client.get_snapshot_ticker(
            "stocks", symbol
        )
        return pd.Timestamp(
            snapshot.last_trade.sip_timestamp, unit="ns", tz="UTC"
        ).tz_convert(clock.NY)

    def get_trading_day(
        self, symbol: str, now: pd.Timestamp, offset: int
    ) -> pd.Timestamp:
        """Raise NotImplementedError, as day offsets are unsupported.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The reference time.
        offset: int
            The number of trading days to shift.
        """
        raise NotImplementedError("get_trading_day")

    def trading_days_slice(self, symbol: str, slice) -> slice:
        """Raise NotImplementedError, as slicing by days is unsupported.

        Parameters
        ----------
        symbol: str
            The symbol.
        slice
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
