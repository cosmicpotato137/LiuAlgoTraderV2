"""Alpaca market data provider.

Classes
-------
AlpacaData
    Market data provider for the Alpaca REST and crypto APIs.
"""

import asyncio
import concurrent.futures
import logging
import time
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd
import pandas_market_calendars
from alpaca.common.enums import BaseURL
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment
from alpaca.data.historical import (CryptoHistoricalDataClient,
                                    StockHistoricalDataClient)
from alpaca.data.models import BarSet
from alpaca.data.requests import (CryptoBarsRequest, StockBarsRequest,
                                  StockSnapshotRequest)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset, Calendar
from alpaca.trading.requests import GetAssetsRequest, GetCalendarRequest

from liualgotrader.common import clock
from liualgotrader.common.types import TimeScale
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.alpaca.util import (alpaca_time, crypto_pair,
                                               is_crypto_symbol)

logger = logging.getLogger(__name__)

_MINUTE = TimeFrame(1, TimeFrameUnit.Minute)
_DAY = TimeFrame(1, TimeFrameUnit.Day)
_BAR_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
]
# snapshot keys in the framework and in the Alpaca API
_SNAPSHOT_FIELDS = {
    "latest_trade": "latestTrade",
    "latest_quote": "latestQuote",
    "minute_bar": "minuteBar",
    "daily_bar": "dailyBar",
    "prev_daily_bar": "prevDailyBar",
}


def _request_time(value: Optional[pd.Timestamp]) -> Optional[datetime]:
    """Return a timestamp as a datetime for an Alpaca data request.

    Parameters
    ----------
    value: Optional[pd.Timestamp]
        The time, or None to leave the request bound unset.
    """
    return None if value is None else value.to_pydatetime()


def _integral(values: pd.Series) -> pd.Series:
    """Return a series as int64 if no value is missing or fractional.

    Parameters
    ----------
    values: pd.Series
        The numbers to convert.

    Returns
    -------
    Return values unchanged if the conversion would lose information.
    """
    if values.notna().all() and (values % 1 == 0).all():
        return values.astype("int64")
    return values


def _symbol_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Return the bars of one symbol with the Alpaca bar columns.

    Parameters
    ----------
    bars: pd.DataFrame
        The bars of one symbol, from BarSet.df without the symbol level.

    Returns
    -------
    Return a DataFrame indexed by New York time with the open, high, low,
    close, volume, trade_count and vwap columns, where missing columns are
    NaN, and volume and trade_count are integers when no value is missing or
    fractional.
    """
    bars = bars.reindex(columns=_BAR_COLUMNS)
    bars.index = bars.index.tz_convert(clock.NY)
    bars["volume"] = _integral(bars["volume"])
    bars["trade_count"] = _integral(bars["trade_count"])
    return bars


def _to_framework_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Return the bars of one symbol in the framework's bar format.

    Parameters
    ----------
    bars: pd.DataFrame
        The bars, with the index and columns of _symbol_bars.

    Returns
    -------
    Return a DataFrame in New York time with the open, high, low, close,
    volume, count, average and vwap columns, where average is the
    volume-weighted price and vwap is NaN.
    """
    data = bars.copy()
    data["average"] = data.vwap
    data["count"] = data.trade_count
    data["vwap"] = np.nan
    return data[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "count",
            "average",
            "vwap",
        ]
    ]


class AlpacaData(DataAPI):
    """Market data provider for the Alpaca REST and crypto APIs.

    Supports US equities and the Bitcoin and Ethereum US dollar pairs.
    Methods that need a REST client raise AssertionError if it is not set.

    Attributes
    ----------
    config: AlpacaConfig
        The connection settings.
    stock_data_client: StockHistoricalDataClient
        The Alpaca client for equity bars.
    raw_stock_data_client: StockHistoricalDataClient
        The Alpaca client for equity snapshots, which returns the raw API
        data.
    crypto_data_client: CryptoHistoricalDataClient
        The Alpaca client for crypto bars.
    trading_client: TradingClient
        The Alpaca client for the asset list and the market calendar.
    symbol_chunk_size
        The number of symbols per snapshot request.
    datetime_cache: Dict[pd.Timestamp, pd.Timestamp]
        The adjusted slice bounds, keyed by requested timestamp.

    Methods
    -------
    get_symbols
        Return the active, tradable US equity symbols.
    get_market_snapshot
        Return snapshots of the tradable US equities.
    get_last_trading
        Return the time of the most recent trade.
    get_trading_day
        Return a timestamp shifted by trading days.
    num_trading_minutes
        Return the trading minutes in one day.
    num_trading_days
        Return the trading days in a date range.
    get_max_data_points_per_load
        Return the data point limit per request.
    trading_days_slice
        Adjust a timestamp slice to trading sessions.
    get_symbols_data
        Return historical bars for several symbols.
    get_symbol_data
        Return historical bars for one symbol.
    """

    def __init__(self, config: AlpacaConfig):
        """Initialize the Alpaca REST clients.

        Parameters
        ----------
        config: AlpacaConfig
            The connection settings.

        Raises
        ------
        Raise ValueError if the API key or secret is not configured, and
        AssertionError if a client cannot be created.
        """
        self.config = config
        self.stock_data_client = StockHistoricalDataClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
        )
        self.raw_stock_data_client = StockHistoricalDataClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
            raw_data=True,
        )
        self.crypto_data_client = CryptoHistoricalDataClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
        )
        base_url = self._trading_base_url()
        self.trading_client = TradingClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
            paper="paper" in base_url,
            url_override=base_url,
        )
        if not (
            self.stock_data_client
            and self.raw_stock_data_client
            and self.crypto_data_client
            and self.trading_client
        ):
            raise AssertionError(
                "Failed to authenticate Alpaca RESTful client"
            )
        # for requesting market snapshots by chunk of symbols
        self.symbol_chunk_size = 1000
        self.datetime_cache: Dict[pd.Timestamp, pd.Timestamp] = {}

    def _trading_base_url(self) -> str:
        """Return the configured trading API base URL.

        Returns
        -------
        Return the URL without a trailing slash or API version, or the live
        trading URL if config.base_url is not set.
        """
        base_url = self.config.base_url or BaseURL.TRADING_LIVE.value
        return base_url.rstrip("/").removesuffix("/v2")

    def get_symbols(self) -> List[str]:
        """Return the symbols of all active, tradable US equities."""
        if not self.trading_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        assets = cast(
            List[Asset],
            self.trading_client.get_all_assets(
                GetAssetsRequest(
                    status=AssetStatus.ACTIVE,
                    asset_class=AssetClass.US_EQUITY,
                )
            ),
        )
        return [asset.symbol for asset in assets if asset.tradable]

    async def get_market_snapshot(
        self, filter_func: Optional[Callable] = None
    ) -> List[Dict]:
        """Return snapshots of all active, tradable US equities.

        Each snapshot is a dictionary with a "ticker" key and the raw data of
        each snapshot component.

        Parameters
        ----------
        filter_func: Optional[Callable], default None
            A predicate that selects the snapshots to keep, or None to keep
            all.
        """
        # parse market snapshots per chunk of symbols
        symbols = self.get_symbols()
        return await self._get_symbols_snapshot(symbols, filter_func)

    async def _get_symbols_snapshot(
        self, symbols: List[str], filter_func: Optional[Callable]
    ) -> List[Dict]:
        """Return the market snapshots for the given symbols.

        Drop snapshots that lack a component when filter_func is set, and
        return them as None otherwise.

        Parameters
        ----------
        symbols: List[str]
            The symbols to fetch.
        filter_func: Optional[Callable]
            A predicate that selects the snapshots to keep, or None to keep
            all.
        """

        def _parse_ticker_snapshot(
            _ticker: str, _ticket_snapshot: Optional[Dict]
        ) -> Optional[Dict]:
            """Return a snapshot as a dictionary, or None if incomplete.

            Parameters
            ----------
            _ticker: str
                The symbol of the snapshot.
            _ticket_snapshot: Optional[Dict]
                The raw Alpaca snapshot, or None if there is none.
            """
            sub_snapshots = {
                sub_snapshot_type: (_ticket_snapshot or {}).get(api_key)
                for sub_snapshot_type, api_key in _SNAPSHOT_FIELDS.items()
            }
            # skip if some snapshot type is missing (e.g. "prevDailyBar": None)
            if not all(sub_snapshots.values()):
                return None

            return {"ticker": _ticker, **sub_snapshots}

        def _parse_snapshot_and_filter(_symbols: List[str]) -> List[Dict]:
            """Return the parsed snapshots for a chunk of symbols.

            When the enclosing filter_func is set, keep only the snapshots it
            accepts, excluding missing ones.

            Parameters
            ----------
            _symbols: List[str]
                The symbols to fetch.
            """
            snapshots = cast(
                Dict[str, Optional[Dict]],
                self.raw_stock_data_client.get_stock_snapshot(
                    StockSnapshotRequest(symbol_or_symbols=_symbols)
                ),
            )
            processed_tickers_snapshot = map(
                lambda key_and_val: _parse_ticker_snapshot(*key_and_val),
                snapshots.items(),
            )
            return list(
                filter(
                    lambda snapshot: (  # type: ignore
                        (snapshot is not None) and (filter_func(snapshot))
                    ),
                    list(processed_tickers_snapshot),  # type : ignore
                )
                if filter_func is not None
                else processed_tickers_snapshot
            )

        # request snapshots per chunk of tickers by concurrency
        with concurrent.futures.ThreadPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            futures = [
                loop.run_in_executor(
                    executor,
                    _parse_snapshot_and_filter,
                    symbols[symbol_idx : symbol_idx + self.symbol_chunk_size],
                )
                for symbol_idx in range(
                    0, len(symbols), self.symbol_chunk_size
                )
            ]

            market_snapshots = [
                y for x in await asyncio.gather(*futures) for y in x
            ]

        return market_snapshots

    def _localize_start_end(
        self, start: date, end: date
    ) -> Tuple[pd.Timestamp, Optional[pd.Timestamp]]:
        """Return a date range as timestamps at midnight in New York.

        Parameters
        ----------
        start: date
            The first date.
        end: date
            The last date; a date of today or later gives an end of None.

        Returns
        -------
        Return the start and the end, where an end of None leaves the end of
        a request unset, so that Alpaca returns data up to the latest time the
        subscription permits.
        """
        return (
            pd.Timestamp(start, tz=clock.NY),
            (None if end >= clock.today() else pd.Timestamp(end, tz=clock.NY)),
        )

    def get_last_trading(self, symbol: str) -> pd.Timestamp:
        """Return the time of the most recent trade for a symbol.

        Parameters
        ----------
        symbol: str
            The symbol to look up.

        Returns
        -------
        Return the current New York time for crypto pairs.

        Raises
        ------
        Raise ValueError if the latest trade is unavailable.
        """
        if not self.raw_stock_data_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        if is_crypto_symbol(symbol):
            return clock.now()
        try:
            snapshots = cast(
                Dict[str, Optional[Dict]],
                self.raw_stock_data_client.get_stock_snapshot(
                    StockSnapshotRequest(symbol_or_symbols=symbol)
                ),
            )
        except APIError as e:
            raise ValueError(f"{symbol} snapshot not found") from e

        snapshot_data = next(iter(snapshots.values()), None) or {}
        min_bar = snapshot_data.get("latestTrade")
        if not min_bar:
            raise ValueError(f"Can't get snapshot for {symbol}")

        return alpaca_time(min_bar["t"])

    def _get_trading_holidays(self) -> List[str]:
        """Return the holiday dates of the NYSE calendar."""
        nyse = pandas_market_calendars.get_calendar("NYSE")
        return nyse.holidays().holidays

    def get_trading_day(
        self, symbol: str, now: pd.Timestamp, offset: int
    ) -> pd.Timestamp:
        """Return a reference time shifted by a number of trading days.

        Shift crypto pairs by offset calendar days and other symbols by offset
        minus one NYSE trading days.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        now: pd.Timestamp
            The reference time.
        offset: int
            The number of days to shift by.
        """
        if is_crypto_symbol(symbol):
            return now + pd.Timedelta(days=offset)
        return now + pd.tseries.offsets.CustomBusinessDay(
            n=offset - 1, holidays=self._get_trading_holidays()
        )

    def num_trading_minutes(self, symbol: str, start: date, end: date) -> int:
        """Return the number of trading minutes in one day for a symbol.

        Count 24 hours for crypto pairs and 16 hours for other symbols.

        Parameters
        ----------
        symbol: str
            The symbol whose trading hours apply.
        start: date
            Unused.
        end: date
            Unused.
        """
        return (24 if is_crypto_symbol(symbol) else (20 - 4)) * 60

    def num_trading_days(self, symbol: str, start: date, end: date) -> int:
        """Return the number of trading days in a date range for a symbol.

        Count every calendar day for crypto pairs and only NYSE trading days
        for other symbols.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        start: date
            The first date of the range.
        end: date
            The last date of the range.
        """
        return (
            (end - start).days + 1
            if is_crypto_symbol(symbol)
            else len(
                pd.date_range(
                    start,
                    end,
                    freq=pd.tseries.offsets.CustomBusinessDay(
                        holidays=self._get_trading_holidays()
                    ),
                )
            )
        )

    def get_max_data_points_per_load(self) -> int:
        """Return 10000, the maximum number of data points per request."""
        # Alpaca suggests 10000 points
        return 10000

    def trading_days_slice(self, symbol: str, s: slice) -> slice:
        """Return a timestamp slice adjusted to the trading sessions it spans.

        For other symbols, return a slice between the opening times of its
        first and last trading days, in New York time, and cache the new bounds
        in datetime_cache.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        s: slice
            The slice to adjust, with timestamp bounds.

        Returns
        -------
        Return s unchanged for crypto pairs.
        """
        if not self.trading_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        if is_crypto_symbol(symbol):
            return s

        if s.start in self.datetime_cache and s.stop in self.datetime_cache:
            return slice(
                self.datetime_cache[s.start], self.datetime_cache[s.stop]
            )

        trading_days = cast(
            List[Calendar],
            self.trading_client.get_calendar(
                GetCalendarRequest(start=s.start.date(), end=s.stop.date())
            ),
        )
        # Calendar.open is the naive local opening time on Calendar.date
        new_slice = slice(
            pd.Timestamp(trading_days[0].open).tz_localize(clock.NY),
            pd.Timestamp(trading_days[-1].open).tz_localize(clock.NY),
        )

        self.datetime_cache[s.start] = new_slice.start
        self.datetime_cache[s.stop] = new_slice.stop

        return new_slice

    def _crypto_get_symbol_data(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: Optional[pd.Timestamp],
        timeframe: TimeFrame,
    ) -> pd.DataFrame:
        """Return historical bars for a crypto pair.

        Parameters
        ----------
        symbol: str
            The crypto pair, with or without a slash.
        start: pd.Timestamp
            The start of the range.
        end: Optional[pd.Timestamp]
            The end of the range, or None for the latest data.
        timeframe: TimeFrame
            A one-day TimeFrame for daily bars, or any other value for minute
            bars.

        Returns
        -------
        Return a DataFrame indexed by New York time, with the columns in
        alphabetical order, including a timestamp column. Return an empty
        DataFrame if there are no bars.

        Raises
        ------
        Raise APIError if a request fails.
        """
        bars = cast(
            BarSet,
            self.crypto_data_client.get_crypto_bars(
                CryptoBarsRequest(
                    symbol_or_symbols=crypto_pair(symbol),
                    timeframe=(
                        _DAY if str(timeframe) == str(_DAY) else _MINUTE
                    ),
                    start=start.to_pydatetime(),
                    end=_request_time(end),
                )
            ),
        ).df
        if bars.empty:
            return pd.DataFrame()

        df = _symbol_bars(bars.droplevel("symbol"))
        df["timestamp"] = df.index
        return df.sort_index(axis=1)

    def _get_stock_bars(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: pd.Timestamp,
        end: Optional[pd.Timestamp],
    ) -> pd.DataFrame:
        """Return historical bars for an equity symbol.

        Parameters
        ----------
        symbol: str
            The symbol to load.
        timeframe: TimeFrame
            The bar resolution.
        start: pd.Timestamp
            The start of the range.
        end: Optional[pd.Timestamp]
            The end of the range, or None for the latest data.

        Returns
        -------
        Return a DataFrame with the index and columns of _symbol_bars, or an
        empty DataFrame if there are no bars.

        Raises
        ------
        Raise APIError if a request fails.
        """
        bars = cast(
            BarSet,
            self.stock_data_client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=timeframe,
                    start=start.to_pydatetime(),
                    end=_request_time(end),
                    adjustment=Adjustment.ALL,
                )
            ),
        ).df
        return bars if bars.empty else _symbol_bars(bars.droplevel("symbol"))

    def get_symbols_data(
        self,
        symbols: List[str],
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> Dict[str, pd.DataFrame]:
        """Return historical bars for several symbols.

        Retry on transient HTTP errors.

        Parameters
        ----------
        symbols: List[str]
            The list of symbols to load.
        start: date
            The start of the date range.
        end: Optional[date], default None
            The end of the date range, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            The bar resolution.

        Returns
        -------
        Return a dictionary that maps each symbol found to a DataFrame of the
        form returned by get_symbol_data.

        Raises
        ------
        Raise AssertionError if symbols is not a list, and APIError if a
        request fails for a reason other than a transient HTTP error.
        """
        if not self.stock_data_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")
        if not isinstance(symbols, list):
            raise AssertionError(f"{symbols} must be a list")

        end = end or clock.today()
        _start, _end = self._localize_start_end(
            start,
            end + pd.Timedelta(days=1) if scale == TimeScale.minute else end,
        )
        try:
            data = cast(
                BarSet,
                self.stock_data_client.get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=symbols,
                        timeframe=(
                            _MINUTE if scale == TimeScale.minute else _DAY
                        ),
                        start=_start.to_pydatetime(),
                        end=_request_time(_end),
                        limit=1000000000,
                        adjustment=Adjustment.ALL,
                    )
                ),
            ).df
        except APIError as e:
            logger.warning("received APIError: %s", e)
            if e.status_code in (500, 502, 504, 429):
                logger.warning("retrying")
                time.sleep(10)
                return self.get_symbols_data(symbols, start, end, scale)
            raise

        if data.empty:
            return {}

        return {
            symbol: _to_framework_bars(
                _symbol_bars(data.xs(symbol, level="symbol"))
            )
            for symbol in data.index.unique(level="symbol")
        }

    def get_symbol_data(
        self,
        symbol: str,
        start: date,
        end: Optional[date] = None,
        scale: TimeScale = TimeScale.minute,
    ) -> pd.DataFrame:
        """Return historical bars for an equity symbol or crypto pair.

        Retry on transient HTTP errors.

        Parameters
        ----------
        symbol: str
            The symbol to load.
        start: date
            The start of the date range.
        end: Optional[date], default None
            The end of the date range, or None for today in New York.
        scale: TimeScale, default TimeScale.minute
            The bar resolution.

        Returns
        -------
        Return a DataFrame in New York time with the open, high, low, close,
        volume, count, average and vwap columns, where average is the
        volume-weighted price and vwap is NaN.

        Raises
        ------
        Raise ValueError if the data cannot be loaded or is empty.
        """
        _start, _end = self._localize_start_end(start, end or clock.today())

        if not self.stock_data_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        t = _DAY if scale == TimeScale.day else _MINUTE

        try:
            if self.config.detailed_dl_debug_enabled:
                logger.info(
                    "symbol=%s, timeframe=%s, range=(%s, %s)",
                    symbol,
                    t,
                    _start,
                    _end or "now",
                )

            data = (
                self._crypto_get_symbol_data(
                    symbol=symbol, start=_start, end=_end, timeframe=t
                )
                if is_crypto_symbol(symbol)
                else self._get_stock_bars(symbol, t, _start, _end)
            )
        except APIError as e:
            logger.warning("received APIError: %s", e)
            if e.status_code in (500, 502, 504, 429):
                logger.warning("retrying")
                time.sleep(10)
                return self.get_symbol_data(symbol, start, end, scale)
            else:
                raise ValueError(
                    f"[EXCEPTION] {e} for {symbol} could not obtain data for {_start} to {_end or 'now'} w {scale.name}"
                ) from e

        except Exception as e:
            raise ValueError(
                f"[EXCEPTION] {e} for {symbol} has no data for {_start} to {_end or 'now'} w {scale.name}"
            ) from e
        else:
            if data.empty:
                raise ValueError(
                    f"[ERROR] {symbol} has no data for {_start} to {_end or 'now'} w {scale.name}"
                )

        return _to_framework_bars(data)
