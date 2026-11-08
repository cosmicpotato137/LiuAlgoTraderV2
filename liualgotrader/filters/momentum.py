"""Momentum stock filter.

Classes
-------
Momentum
    Filter that selects stocks showing strong upward momentum.
"""

import logging
from typing import Callable, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select

from liualgotrader.common import clock, config
from liualgotrader.db.models.trending_tickers import TrendingTicker
from liualgotrader.db.session import session_scope
from liualgotrader.strategy.new_base import Filter
from liualgotrader.vendors.alpaca.data import AlpacaData
from liualgotrader.vendors.polygon.data import PolygonData

logger = logging.getLogger(__name__)


class Momentum(Filter):
    """Filter that selects stocks showing strong upward momentum.

    A live run filters the market snapshot by share price, previous day dollar
    volume, change from the previous close and volume, and needs the context
    to have a trader. A backtest run returns the symbols that the live trader
    recorded for a filter of the same name.

    Attributes
    ----------
    max_share_price: float
        The highest share price to select.
    min_share_price: float
        The lowest share price to select.
    min_last_dv: float
        The previous day dollar volume a symbol must exceed.
    min_volume: float
        The current volume a symbol must exceed.
    today_change_percent: float
        The lowest percentage change to select.
    from_market_open: float
        The from-market-open setting; stored but unused.
    max_symbols: int
        The maximum number of symbols; stored but unused.
    trade_able_symbols
        The tradeable symbols, set by a live run.

    Methods
    -------
    _apply_filter_on_market_snapshot
        Return the snapshot tickers that pass a filter.
    _load_from_db
        Return the symbols recorded for the filter at a time.
    _momentum_filter
        Return whether a snapshot entry meets the criteria.
    _polygon_snapshot_details
        Return the filter values of a Polygon entry.
    _alpaca_snapshot_details
        Return the filter values of an Alpaca entry.
    run
        Return the symbols selected by the filter (overrides Filter).
    """

    def __init__(
        self,
        max_share_price: float,
        min_share_price: float,
        min_last_dv: float,
        today_change_percent: float,
        min_volume: float,
        from_market_open: float,
        max_symbols: int = config.total_tickers,
        **kwargs,
    ):
        """Initialize the momentum filter and its thresholds.

        Parameters
        ----------
        max_share_price: float
            The highest share price to select.
        min_share_price: float
            The lowest share price to select.
        min_last_dv: float
            The previous day dollar volume a symbol must exceed.
        today_change_percent: float
            The lowest percentage change from the previous close to select.
        min_volume: float
            The current volume a symbol must exceed.
        from_market_open: float
            The from-market-open setting; stored but unused.
        max_symbols: int, default config.total_tickers
            The maximum number of symbols; stored but unused.
        """
        super().__init__(**kwargs)
        self.max_share_price = max_share_price
        self.min_share_price = min_share_price
        self.min_last_dv = min_last_dv
        self.min_volume = min_volume
        self.today_change_percent = today_change_percent
        self.from_market_open = from_market_open
        self.max_symbols = max_symbols

    async def _get_trade_able_symbols(self) -> List[str]:
        """Return the tradeable symbols reported by the trader of the context.

        Raises
        ------
        Raise AssertionError if the context has no trader.
        """
        if self.ctx.trader is None:
            raise AssertionError("the momentum filter needs a trader")
        symbols = await self.ctx.trader.get_tradeable_symbols()
        logger.info(
            "loaded list of %s trade-able symbols from %s",
            len(symbols),
            self.ctx.trader,
        )
        return symbols

    async def _apply_filter_on_market_snapshot(
        self, filter_func: Optional[Callable]
    ) -> List[str]:
        """Return the tickers in the market snapshot that pass a filter.

        Parameters
        ----------
        filter_func: Optional[Callable]
            The predicate that selects snapshot entries, or None.
        """
        filtered = await self.ctx.data_loader.data_api.get_market_snapshot(
            filter_func
        )
        logger.info(
            "loaded %s tickers of market snapshots after momentum filtering",
            len(filtered),
        )
        if not len(filtered):
            logger.warning(
                "failed to load any market snapshots for any tickers"
            )
            return []

        return [x["ticker"] for x in filtered]

    async def _load_from_db(self, back_time: pd.Timestamp) -> List[str]:
        """Return the symbols recorded for this filter around a given time.

        For midnight, return the symbols recorded from back_time to one day
        later; otherwise, those recorded from 9:30 that day to one minute after
        back_time.

        Parameters
        ----------
        back_time: pd.Timestamp
            The moment to load symbols for; midnight selects a whole day.
        """
        daily_scale = back_time.hour == 0
        start = (
            back_time if daily_scale else clock.market_open(back_time.date())
        )
        end = (
            pd.Timestamp(back_time.date() + pd.Timedelta(days=1), tz=clock.NY)
            if daily_scale
            else back_time + pd.Timedelta(minutes=1)
        )
        async with session_scope() as session:
            symbols = list(
                await session.scalars(
                    select(TrendingTicker.symbol).where(
                        TrendingTicker.scanner_name == self.name,
                        TrendingTicker.create_tstamp >= start,
                        TrendingTicker.create_tstamp <= end,
                    )
                )
            )

        logger.debug("load from db %s %s %s", start, end, len(symbols))
        return symbols

    def _momentum_filter(self, snapshot) -> bool:
        """Return whether a market snapshot entry meets the momentum criteria.

        Call only after run has set trade_able_symbols.

        Parameters
        ----------
        snapshot
            The snapshot entry, from the Alpaca or Polygon data API.

        Raises
        ------
        Raise ValueError if the data loader uses any other data API.
        """
        if isinstance(self.ctx.data_loader.data_api, AlpacaData):
            (
                tradable,
                last_trade_price,
                prev_day_volume_price,
                today_gap_up_pct,
                today_volume,
            ) = self._alpaca_snapshot_details(snapshot)
        elif isinstance(self.ctx.data_loader.data_api, PolygonData):
            (
                tradable,
                last_trade_price,
                prev_day_volume_price,
                today_gap_up_pct,
                today_volume,
            ) = self._polygon_snapshot_details(snapshot)
        else:
            raise ValueError(
                f"Invalid data API: {type(self.ctx.data_loader.data_api)}"
            )

        in_price_range = (
            self.max_share_price >= last_trade_price >= self.min_share_price
        )
        return (
            tradable
            and in_price_range
            and prev_day_volume_price > self.min_last_dv
            and today_gap_up_pct >= self.today_change_percent
            and today_volume > self.min_volume
        )

    def _polygon_snapshot_details(
        self, snapshot
    ) -> Tuple[bool, float, float, float, float]:
        """Return the momentum filter values of a Polygon snapshot entry.

        Parameters
        ----------
        snapshot
            The Polygon snapshot entry.

        Returns
        -------
        Return whether the ticker is tradeable, the last trade price, the
        previous day dollar volume, today's change percentage and today's
        volume.
        """
        tradeable = snapshot["ticker"].lower() in self.trade_able_symbols
        last_trade_price = float(snapshot["lastTrade"]["p"])
        prev_day_volume_price = float(snapshot["prevDay"]["p"]) * float(
            snapshot["prevDay"]["v"]
        )
        today_gap_up_pct = snapshot["todaysChangePerc"]
        today_volume = snapshot["day"]["v"]

        return (
            tradeable,
            last_trade_price,
            prev_day_volume_price,
            today_gap_up_pct,
            today_volume,
        )

    def _alpaca_snapshot_details(
        self, snapshot
    ) -> Tuple[bool, float, float, float, float]:
        """Return the momentum filter values of an Alpaca snapshot entry.

        Parameters
        ----------
        snapshot
            The Alpaca snapshot entry.

        Returns
        -------
        Return whether the ticker is tradeable, the latest trade price, the
        previous day dollar volume, the percentage gap between today's open and
        the previous close, and today's volume.
        """
        tradable = snapshot["ticker"].lower() in self.trade_able_symbols

        last_trade_price = float(snapshot["latest_trade"]["p"])
        prev_day_price_volume = float(snapshot["prev_daily_bar"]["v"]) * float(
            snapshot["prev_daily_bar"]["c"]
        )
        today_gap_up_pct = (
            100.0
            * (snapshot["daily_bar"]["o"] - snapshot["prev_daily_bar"]["c"])
            / snapshot["prev_daily_bar"]["c"]
        )
        today_volume = snapshot["daily_bar"]["v"]

        return (
            tradable,
            last_trade_price,
            prev_day_price_volume,
            today_gap_up_pct,
            today_volume,
        )

    async def run(self, now: pd.Timestamp) -> List[str]:
        """Return the symbols selected by the momentum filter at a time.

        When live, refresh trade_able_symbols and filter the market snapshot;
        when backtesting, return the symbols recorded in the database.

        Parameters
        ----------
        now: pd.Timestamp
            The time to select as of.
        """
        if not self.ctx.backtesting:
            self.trade_able_symbols = await self._get_trade_able_symbols()
            return await self._apply_filter_on_market_snapshot(
                self._momentum_filter
            )

        rows = await self._load_from_db(now)

        logger.info(
            "Filter %s -> now=%s picked %s",
            self.name,
            now,
            len(rows),
        )
        return rows
