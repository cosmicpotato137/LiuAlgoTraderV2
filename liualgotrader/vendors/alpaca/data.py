"""Alpaca market data provider.

Classes
-------
AlpacaData
    Market data provider for the Alpaca REST and crypto APIs.
"""

import asyncio
import concurrent.futures
import time
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd
import pandas_market_calendars
import pytz
from alpaca.common.enums import BaseURL
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment
from alpaca.data.historical import (
    CryptoHistoricalDataClient,
    StockHistoricalDataClient,
)
from alpaca.data.models import BarSet
from alpaca.data.requests import (
    CryptoBarsRequest,
    StockBarsRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset, Calendar
from alpaca.trading.requests import GetAssetsRequest, GetCalendarRequest
from dateutil.parser import parse as date_parser

from liualgotrader.common.tlog import tlog
from liualgotrader.common.types import TimeScale
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.alpaca.config import AlpacaConfig

NY = "America/New_York"
nytz = pytz.timezone(NY)

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


def _is_crypto_symbol(symbol: str) -> bool:
    """Return whether a symbol is a supported crypto pair.

    Only the Bitcoin and Ethereum pairs quoted in US dollars are supported.

    Parameters
    ----------
    symbol: str
        The symbol to check, with or without a slash, in any case.
    """
    return symbol.lower() in {"eth/usd", "btc/usd", "ethusd", "btcusd"}


def _crypto_pair(symbol: str) -> str:
    """Return a crypto pair in the upper-case, slash-separated Alpaca form.

    Parameters
    ----------
    symbol: str
        The crypto pair, with or without a slash, in any case.
    """
    if "/" not in symbol:
        symbol = f"{symbol[:3]}/{symbol[3:]}"
    return symbol.upper()


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
    Return a DataFrame indexed by UTC timestamp with the open, high, low,
    close, volume, trade_count and vwap columns, where missing columns are
    NaN, and volume and trade_count are integers when no value is missing or
    fractional.
    """
    bars = bars.reindex(columns=_BAR_COLUMNS)
    bars.index = bars.index.tz_convert("UTC")
    bars["volume"] = _integral(bars["volume"])
    bars["trade_count"] = _integral(bars["trade_count"])
    return bars


def _to_framework_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Return the bars of one symbol in the framework's bar format.

    Parameters
    ----------
    bars: pd.DataFrame
        The bars, indexed by timestamp, with the columns of _symbol_bars.

    Returns
    -------
    Return a DataFrame in New York time with the open, high, low, close,
    volume, count, average and vwap columns, where average is the
    volume-weighted price and vwap is NaN.
    """
    data = bars.tz_convert(NY)
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
    datetime_cache: Dict[datetime, datetime]
        The adjusted slice bounds, keyed by requested datetime.

    Methods
    -------
    get_symbols
        Return the active, tradable US equity symbols.
    get_market_snapshot
        Return snapshots of the tradable US equities.
    get_last_trading
        Return the time of the most recent trade.
    get_trading_day
        Return a datetime shifted by trading days.
    num_trading_minutes
        Return the trading minutes in one day.
    num_trading_days
        Return the trading days in a date range.
    get_max_data_points_per_load
        Return the data point limit per request.
    trading_days_slice
        Adjust a datetime slice to trading sessions.
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
        self.datetime_cache: Dict[datetime, datetime] = {}

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

    def _localize_start_end(self, start: date, end: date) -> Tuple[str, str]:
        """Return a date range as ISO 8601 strings in New York time.

        Parameters
        ----------
        start: date
            The first date, converted to midnight.
        end: date
            The last date, converted to midnight, or to the current time if it
            is today or later.
        """
        return (
            nytz.localize(
                datetime.combine(start, datetime.min.time())
            ).isoformat(),
            (
                nytz.localize(
                    datetime.now().replace(microsecond=0)
                ).isoformat()
                if end >= date.today()
                else nytz.localize(
                    datetime.combine(end, datetime.min.time())
                ).isoformat()
            ),
        )

    def get_last_trading(self, symbol: str) -> datetime:
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

        if _is_crypto_symbol(symbol):
            return datetime.now(tz=nytz)
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

        return pd.Timestamp(min_bar["t"]).tz_convert(NY)

    def _get_trading_holidays(self) -> List[str]:
        """Return the holiday dates of the NYSE calendar."""
        nyse = pandas_market_calendars.get_calendar("NYSE")
        return nyse.holidays().holidays

    def get_trading_day(
        self, symbol: str, now: datetime, offset: int
    ) -> datetime:
        """Return a reference time shifted by a number of trading days.

        Shift crypto pairs by offset calendar days and other symbols by offset
        minus one NYSE trading days.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        now: datetime
            The reference datetime, treated as New York time if naive.
        offset: int
            The number of days to shift by.
        """
        if _is_crypto_symbol(symbol):
            cbd_offset = timedelta(days=offset)
        else:
            cbd_offset = pd.tseries.offsets.CustomBusinessDay(
                n=offset - 1, holidays=self._get_trading_holidays()
            )
        return (
            nytz.localize(now + cbd_offset)
            if now.tzinfo is None
            else now + cbd_offset
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
        return (24 if _is_crypto_symbol(symbol) else (20 - 4)) * 60

    def num_trading_days(self, symbol: str, start: date, end: date) -> int:
        """Return the number of trading days in a date range for a symbol.

        Count every calendar day for crypto pairs and only NYSE trading days
        for other symbols.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        start: date
            The first date of the range, as a date or a string.
        end: date
            The last date of the range, as a date or a string.
        """
        if type(start) == str:
            start = date_parser(start)  # type: ignore
        if type(end) == str:
            end = date_parser(end)  # type: ignore

        return (
            (end - start).days + 1
            if _is_crypto_symbol(symbol)
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
        """Return a datetime slice adjusted to the trading sessions it spans.

        For other symbols, return a slice between the opening times of its
        first and last trading days, in New York time, and cache the new bounds
        in datetime_cache.

        Parameters
        ----------
        symbol: str
            The symbol whose trading calendar applies.
        s: slice
            The slice to adjust, with datetime bounds.

        Returns
        -------
        Return s unchanged for crypto pairs.
        """
        if not self.trading_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        if _is_crypto_symbol(symbol):
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
            nytz.localize(trading_days[0].open),
            nytz.localize(trading_days[-1].open),
        )

        self.datetime_cache[s.start] = new_slice.start
        self.datetime_cache[s.stop] = new_slice.stop

        return new_slice

    def _crypto_get_symbol_data(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: TimeFrame,
    ) -> pd.DataFrame:
        """Return historical bars for a crypto pair.

        Parameters
        ----------
        symbol: str
            The crypto pair, with or without a slash.
        start: str
            The start of the range, as an ISO 8601 string.
        end: str
            The end of the range, as an ISO 8601 string.
        timeframe: TimeFrame
            A one-day TimeFrame for daily bars, or any other value for minute
            bars.

        Returns
        -------
        Return a DataFrame indexed by UTC timestamp, with the columns in
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
                    symbol_or_symbols=_crypto_pair(symbol),
                    timeframe=(
                        _DAY if str(timeframe) == str(_DAY) else _MINUTE
                    ),
                    start=pd.Timestamp(start).to_pydatetime(),
                    end=pd.Timestamp(end).to_pydatetime(),
                )
            ),
        ).df
        if bars.empty:
            return pd.DataFrame()

        df = _symbol_bars(bars.droplevel("symbol"))
        df["timestamp"] = df.index
        return df.sort_index(axis=1)

    def _get_stock_bars(
        self, symbol: str, timeframe: TimeFrame, start: str, end: str
    ) -> pd.DataFrame:
        """Return historical bars for an equity symbol.

        Parameters
        ----------
        symbol: str
            The symbol to load.
        timeframe: TimeFrame
            The bar resolution.
        start: str
            The start of the range, as an ISO 8601 string.
        end: str
            The end of the range, as an ISO 8601 string.

        Returns
        -------
        Return a DataFrame indexed by UTC timestamp with the columns of
        _symbol_bars, or an empty DataFrame if there are no bars.

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
                    start=pd.Timestamp(start).to_pydatetime(),
                    end=pd.Timestamp(end).to_pydatetime(),
                    limit=1000000,
                    adjustment=Adjustment.ALL,
                )
            ),
        ).df
        return bars if bars.empty else _symbol_bars(bars.droplevel("symbol"))

    def get_symbols_data(
        self,
        symbols: List[str],
        start: date,
        end: date = date.today(),
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
        end: date, default date.today()
            The end of the date range.
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

        _start, _end = self._localize_start_end(
            start,
            end + timedelta(days=1) if scale == TimeScale.minute else end,
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
                        start=pd.Timestamp(_start).to_pydatetime(),
                        end=pd.Timestamp(_end).to_pydatetime(),
                        limit=1000000000,
                        adjustment=Adjustment.ALL,
                    )
                ),
            ).df
        except APIError as e:
            tlog(f"received APIError: {e}")
            if e.status_code in (500, 502, 504, 429):
                tlog("retrying")
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
        end: date = date.today(),
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
        end: date, default date.today()
            The end of the date range.
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
        _start, _end = self._localize_start_end(start, end)

        if not self.stock_data_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")

        t = _DAY if scale == TimeScale.day else _MINUTE

        try:
            if self.config.detailed_dl_debug_enabled:
                tlog(f"symbol={symbol}, timeframe={t}, range=({_start, _end})")

            data = (
                self._crypto_get_symbol_data(
                    symbol=symbol, start=_start, end=_end, timeframe=t
                )
                if _is_crypto_symbol(symbol)
                else self._get_stock_bars(symbol, t, _start, _end)
            )
        except APIError as e:
            tlog(f"received APIError: {e}")
            if e.status_code in (500, 502, 504, 429):
                tlog("retrying")
                time.sleep(10)
                return self.get_symbol_data(symbol, start, end, scale)
            else:
                raise ValueError(
                    f"[EXCEPTION] {e} for {symbol} could not obtain data for {_start} to {_end} w {scale.name}"
                ) from e

        except Exception as e:
            raise ValueError(
                f"[EXCEPTION] {e} for {symbol} has no data for {_start} to {_end} w {scale.name}"
            ) from e
        else:
            if data.empty:
                raise ValueError(
                    f"[ERROR] {symbol} has no data for {_start} to {_end} w {scale.name}"
                )

        return _to_framework_bars(data)
