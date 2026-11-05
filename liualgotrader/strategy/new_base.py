"""Strategy components: filters, indicators, signals and rules.

Filters select the symbols to trade. Indicators compute values from market
data. Signals turn indicator values into predictions of price movement for
the symbols that their filters selected. Rules turn signals and positions into
order requests, which the runtime executes: the consumer when trading live,
and the backtester otherwise. Components never submit orders themselves.

A filter, a signal and a rule make a Strategy, which the runtime activates
and deactivates as a whole, and which owns the symbols it trades. Each
strategy file of a trade plan describes one strategy, and tradeplan.py
creates the strategies of a trade plan.

Each run creates one Context and passes it to every component. The context
holds the services and caches that components share, so separate runs in the
same process, such as tests or optimizer iterations, do not share state.

Times follow the package convention: tz-aware pd.Timestamp values in New York
time. The now passed to a component is the timestamp of the latest completed
bar, and a component must not read data stamped after it.

Classes
-------
Context
    Per-run services and caches shared by the components of a run.
Component
    Base class of every strategy component.
Filter
    Select the symbols that signals evaluate.
Indicator
    Compute a time series from market data for a symbol.
Signal
    Predict price movement for a symbol.
OrderRequest
    An order that a rule asks the runtime to submit.
Rule
    Base class of rules, which turn signals into order requests.
SymbolRule
    Rule that decides for one symbol at a time.
PortfolioRule
    Rule that decides for all symbols of its signal at once.
Strategy
    A named filter, signal and rule that the runtime runs together.
"""

import json
import logging
import math
from dataclasses import dataclass
from functools import cached_property
from typing import Callable, Optional, Self, TypeVar

import pandas as pd

from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import AssetType, Order, OrderType, Trade
from liualgotrader.market_calendar.base import MarketCalendarAPI
from liualgotrader.market_calendar.factory import market_calendar_factory
from liualgotrader.trade.base import TraderAPI

logger = logging.getLogger(__name__)

T = TypeVar("T", pd.DataFrame, pd.Series)


class Context:
    """Per-run services and caches shared by the components of a run.

    Attributes
    ----------
    data_loader: DataLoader
        The loader of market data.
    trader: Optional[TraderAPI]
        The broker, for read-only queries such as the tradeable or shortable
        symbols, or None.
    backtesting: bool
        Whether the run is a backtest.
    asset_type: AssetType
        The type of asset traded.
    calendar: MarketCalendarAPI
        The market calendar of the asset type, created on first use.
    indicators: dict[str, Indicator]
        The shared indicators, by class and parameters.
    horizon: Optional[pd.Timestamp]
        The time of the latest bar that the runtime has made available, or
        None before the first. Indicators and signals compute through it on
        a cache miss. The live consumer advances it to each minute bar, and
        the backtester to the end of each day, so that a backtest computes
        each result once a day.

    Methods
    -------
    bars
        Return the bars of a symbol from a start time through now.
    set_horizon
        Make the bars stamped through a time available to components.
    invalidate
        Mark the cached results for a symbol as out of date.
    version
        Return the data version of a symbol.
    is_shortable
        Return whether a symbol can be sold short.
    """

    def __init__(
        self,
        data_loader: DataLoader,
        trader: Optional[TraderAPI] = None,
        backtesting: bool = False,
        asset_type: AssetType = AssetType.US_EQUITIES,
    ):
        """Initialize the context with empty caches.

        Parameters
        ----------
        data_loader: DataLoader
            The loader of market data.
        trader: Optional[TraderAPI], default None
            The broker, for read-only queries.
        backtesting: bool, default False
            Whether the run is a backtest.
        asset_type: AssetType, default AssetType.US_EQUITIES
            The type of asset traded, which sets the market calendar.
        """
        self.data_loader = data_loader
        self.trader = trader
        self.backtesting = backtesting
        self.asset_type = asset_type
        self.indicators: dict[str, Indicator] = {}
        self.horizon: Optional[pd.Timestamp] = None
        self._versions: dict[str, int] = {}
        self._shortable: dict[str, bool] = {}
        self._fetched: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    @cached_property
    def calendar(self) -> MarketCalendarAPI:
        """Return the market calendar of the asset type.

        Create the calendar on first use, so that a run that never asks for
        trading days does not connect to the calendar's vendor.

        Raises
        ------
        Raise the exceptions of market_calendar_factory.
        """
        return market_calendar_factory(self.asset_type)

    def bars(
        self, symbol: str, start: pd.Timestamp, now: pd.Timestamp
    ) -> pd.DataFrame:
        """Return the bars of a symbol stamped from start through now.

        Ask the loader only for the part of the range that no earlier call
        asked for, since the loader fetches again when a range starts before
        its first bar, as one starting on a holiday does. Never return a bar
        stamped after now, even when the loader holds later data, as it does
        when backtesting.

        Parameters
        ----------
        symbol: str
            The symbol.
        start: pd.Timestamp
            The time of the first bar.
        now: pd.Timestamp
            The time of the last bar.
        """
        data = self.data_loader[symbol]
        fetched = self._fetched.get(symbol)
        if fetched is None:
            data[start:now]
            fetched = (start, now)
        if start < fetched[0]:
            data[start : fetched[0]]
        if now > fetched[1]:
            data[fetched[1] : now]
        self._fetched[symbol] = (min(start, fetched[0]), max(now, fetched[1]))
        return data.symbol_data.loc[start:now]

    def set_horizon(self, horizon: pd.Timestamp) -> None:
        """Make the bars stamped through a time available to components.

        Never move the horizon back, so that a late bar does not undo a
        later one.

        Parameters
        ----------
        horizon: pd.Timestamp
            The time of the latest available bar.
        """
        if self.horizon is None or horizon > self.horizon:
            self.horizon = horizon

    def invalidate(self, symbol: str) -> None:
        """Mark the cached indicator and signal results for a symbol as stale.

        The runtime calls this method whenever it changes the bars of symbol,
        including updates to the bar of the current minute.

        Parameters
        ----------
        symbol: str
            The symbol whose bars changed.
        """
        self._versions[symbol] = self._versions.get(symbol, 0) + 1

    def version(self, symbol: str) -> int:
        """Return the number of times the bars of a symbol have changed.

        Parameters
        ----------
        symbol: str
            The symbol.
        """
        return self._versions.get(symbol, 0)

    async def is_shortable(self, symbol: str) -> bool:
        """Return whether a symbol can be sold short.

        Ask the trader once per symbol and cache the answer. When backtesting,
        return True, since the broker knows only the current state. Treat a
        failed lookup, or a missing trader, as not shortable.

        Parameters
        ----------
        symbol: str
            The symbol.
        """
        if self.backtesting:
            return True
        if symbol not in self._shortable:
            try:
                self._shortable[symbol] = bool(
                    self.trader and await self.trader.is_shortable(symbol)
                )
            except Exception:
                logger.warning(
                    "could not check whether %s is shortable, assuming it "
                    "is not",
                    symbol,
                    exc_info=True,
                )
                self._shortable[symbol] = False
        return self._shortable[symbol]


class Component:
    """Base class of every strategy component.

    Subclasses take their strategy file settings as keyword arguments and
    pass the remaining keyword arguments on to the base initializer, for
    example ``def __init__(self, window: int = 20, **kwargs)``. An unknown
    setting in the strategy file then raises TypeError instead of being
    ignored.

    Attributes
    ----------
    ctx: Context
        The context of the run.
    name: str
        The name of the component's strategy, or its class name.
    """

    def __init__(self, ctx: Context, name: Optional[str] = None):
        """Initialize the component.

        Parameters
        ----------
        ctx: Context
            The context of the run.
        name: Optional[str], default None
            The name of the component's strategy, or None for the class name.
        """
        self.ctx = ctx
        self.name = name or type(self).__name__

    def __repr__(self):
        """Return the name of the component."""
        return self.name


@dataclass
class _CacheEntry:
    """A result computed for a symbol, and the inputs it is valid for."""

    data: pd.DataFrame | pd.Series
    through: pd.Timestamp
    version: int


class _Memoized(Component):
    """Component whose per-symbol results are cached until the data changes."""

    def __init__(self, **kwargs):
        """Initialize the component with an empty cache."""
        super().__init__(**kwargs)
        self._cache: dict[str, _CacheEntry] = {}

    def _entry(
        self,
        symbol: str,
        now: pd.Timestamp,
        compute: Callable[[str, pd.Timestamp], T],
    ) -> _CacheEntry:
        """Return a cached result for a symbol that covers now.

        Call compute again if the cached result ends before now or the bars of
        symbol changed since it was computed. Compute through the horizon of
        the context, or through now if no bar that late is available yet.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time the result must cover.
        compute: Callable[[str, pd.Timestamp], T]
            The function that computes the result for a symbol through a time.
        """
        version = self.ctx.version(symbol)
        entry = self._cache.get(symbol)
        if entry is None or entry.version != version or entry.through < now:
            through = max(now, self.ctx.horizon or now)
            entry = _CacheEntry(compute(symbol, through), through, version)
            self._cache[symbol] = entry
        return entry

    def _memoized(
        self,
        symbol: str,
        now: pd.Timestamp,
        compute: Callable[[str, pd.Timestamp], T],
    ) -> T:
        """Return the cached result for a symbol through now.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to return.
        compute: Callable[[str, pd.Timestamp], T]
            The function that computes the result for a symbol through a time.
        """
        return self._entry(symbol, now, compute).data.loc[:now]


class _Recurring(Component):
    """Component that runs at a recurrence, or once a day without one."""

    def __init__(self, recurrence: Optional[pd.Timedelta] = None, **kwargs):
        """Initialize the component, which has not run yet.

        Parameters
        ----------
        recurrence: Optional[pd.Timedelta], default None
            The interval between runs, or None to run once a day.
        """
        super().__init__(**kwargs)
        self.recurrence = recurrence
        self.last_run: Optional[pd.Timestamp] = None

    def is_due(self, now: pd.Timestamp) -> bool:
        """Return whether the component runs at a time.

        It runs if it has not run yet, if its recurrence has elapsed since
        its last run, or, without a recurrence, if its last run was on an
        earlier day.

        Parameters
        ----------
        now: pd.Timestamp
            The time.
        """
        if self.last_run is None:
            return True
        if self.recurrence is None:
            return False
        return now - self.last_run >= self.recurrence


class Filter(_Recurring):
    """Select the symbols that signals evaluate.

    Replaces Scanner. Subclasses implement run. Each run replaces the
    filter's universe with the symbols it selects, and the universe lasts
    until the next run, even across days.

    Attributes
    ----------
    recurrence: Optional[pd.Timedelta]
        The interval between runs, or None to run once a day.
    last_run: Optional[pd.Timestamp]
        The time of the last run of select, or None before the first.

    Methods
    -------
    run
        Return the symbols that the filter selects.
    select
        Return the symbols that run selects, in lower case.
    is_due
        Return whether the filter runs at a time.
    """

    async def run(self, now: pd.Timestamp) -> list[str]:
        """Return the symbols that the filter selects at a given time.

        Subclasses must override this method.

        Parameters
        ----------
        now: pd.Timestamp
            The time to select as of, which is in the past when backtesting.
        """
        raise NotImplementedError

    async def select(self, now: pd.Timestamp) -> list[str]:
        """Return the symbols that run selects at a given time, in lower case.

        The runtime calls this method rather than run. Record now as the time
        of the last run.

        Parameters
        ----------
        now: pd.Timestamp
            The time to select as of, which is in the past when backtesting.
        """
        self.last_run = now
        return [symbol.lower() for symbol in await self.run(now)]


class Indicator(_Memoized):
    """Compute a time series from market data for a symbol.

    Subclasses implement compute. Signals and other indicators get instances
    through create, so the context computes each indicator once per symbol,
    whichever signals use it.

    Methods
    -------
    create
        Return the shared indicator with the given parameters.
    compute
        Return the indicator values for a symbol through a time.
    get
        Return the cached indicator values for a symbol through a time.
    """

    @classmethod
    def create(cls, ctx: Context, **params) -> Self:
        """Return the indicator of this class with the given parameters.

        Create the indicator on first use, and return the same instance for
        later calls with the same context, class and parameters. Parameters
        left at their defaults count as different from the same values passed
        explicitly.

        Parameters
        ----------
        ctx: Context
            The context of the run.
        params
            The indicator settings, which must be JSON serializable or have a
            stable repr.
        """
        key = (
            f"{cls.__module__}.{cls.__qualname__}"
            f"{json.dumps(params, sort_keys=True, default=repr)}"
        )
        if key not in ctx.indicators:
            ctx.indicators[key] = cls(ctx=ctx, name=key, **params)
        return ctx.indicators[key]  # type: ignore

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        """Return the indicator values for a symbol through a time.

        Subclasses must override this method. The value of each row must
        depend only on data stamped at or before that row, so that computing
        through a later time yields the same earlier rows. The backtester
        relies on this to compute a whole day at once. So read bars from a
        start anchored to the day of now, such as
        now.normalize() - pd.Timedelta(days=n), rather than to now itself,
        so that the computations of a day share their first bar.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return a DataFrame indexed by bar timestamp.
        """
        raise NotImplementedError

    def get(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        """Return the indicator values for a symbol through a time.

        Compute the values only if no cached result covers now.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to return.
        """
        return self._memoized(symbol, now, self.compute)


class Signal(_Memoized):
    """Predict price movement for a symbol.

    Subclasses create the indicators in their initializer. A signal evaluates
    the symbols that the filter of its strategy selects, and those that its
    strategy holds, for the rule of its strategy. It does not know about
    positions or orders.

    A signal value is a float: a positive value predicts a rise and a negative
    value a fall, and the magnitude, at most 1, is the confidence. NaN means no
    prediction. A row with a value is an event that the runtime passes to the
    signal's rule, so a signal that holds a value on every bar makes its rule
    decide on every bar. The runtime evaluates a signal only when its rule may
    decide, so never once its strategy is inactive.

    Methods
    -------
    compute
        Return the signal values for a symbol through a time.
    get
        Return the cached signal values for a symbol through a time.
    at
        Return the signal value for a symbol at a time.
    fired
        Return whether the signal has a value for a symbol at a time.
    latest
        Return the latest signal value of each of some symbols.
    """

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        """Return the signal values for a symbol through a time.

        Subclasses must override this method. The value of each row must
        depend only on data stamped at or before that row, as for
        Indicator.compute.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return a float Series indexed by bar timestamp.
        """
        raise NotImplementedError

    def get(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        """Return the signal values for a symbol through a time.

        Compute the values only if no cached result covers now.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to return.
        """
        return self._memoized(symbol, now, self.compute)

    def at(self, symbol: str, now: pd.Timestamp) -> float:
        """Return the signal value for a symbol at a time.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the row.

        Returns
        -------
        Return NaN if the signal has no row stamped now.
        """
        return float(
            self._entry(symbol, now, self.compute).data.get(now, math.nan)
        )

    def fired(self, symbol: str, now: pd.Timestamp) -> bool:
        """Return whether the signal has a value for a symbol at a time.

        Log an exception raised for the symbol, and treat it as no value.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the row.
        """
        try:
            return not math.isnan(self.at(symbol, now))
        except Exception:
            logger.exception("signal %s failed on %s", self, symbol)
            return False

    def latest(self, symbols: list[str], now: pd.Timestamp) -> pd.Series:
        """Return the latest signal value at or before a time of each of some
        symbols.

        Log an exception raised for a symbol, and treat it as no value, so
        that one symbol does not keep a rule from deciding on the others.

        Parameters
        ----------
        symbols: list[str]
            The symbols.
        now: pd.Timestamp
            The time.

        Returns
        -------
        Return a float Series indexed by symbol, NaN where the signal has no
        value at or before now.
        """
        return pd.Series(
            [self._latest(symbol, now) for symbol in symbols],
            index=pd.Index(symbols, name="symbol"),
            dtype=float,
            name=self.name,
        )

    def _latest(self, symbol: str, now: pd.Timestamp) -> float:
        """Return the latest value at or before now for a symbol, or NaN."""
        try:
            series = self.get(symbol, now)
        except Exception:
            logger.exception("signal %s failed on %s", self, symbol)
            return math.nan
        last = series.last_valid_index()
        return math.nan if last is None else float(series[last])


@dataclass(frozen=True)
class OrderRequest:
    """An order that a rule asks the runtime to submit.

    Attributes
    ----------
    symbol: str
        The symbol to trade.
    side: Order.FillSide
        Whether to buy or sell.
    qty: float
        The quantity, which must be positive.
    type: OrderType
        OrderType.MARKET or OrderType.LIMIT. Its string value, such as
        "limit", is also accepted and converted.
    limit_price: Optional[float]
        The limit price of a limit order, or None.
    """

    symbol: str
    side: Order.FillSide
    qty: float
    type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None

    def __post_init__(self):
        """Check that the request describes a valid order.

        Raises
        ------
        Raise ValueError if qty is not positive, type is not market or limit,
        or limit_price is missing from a limit order or given for a market
        order.
        """
        if self.qty <= 0:
            raise ValueError(f"qty must be positive, got {self.qty}")
        try:
            # the dataclass is frozen, so set the converted type directly
            object.__setattr__(self, "type", OrderType(self.type))
        except ValueError:
            raise ValueError(f"unknown order type {self.type}") from None
        if self.type not in (OrderType.MARKET, OrderType.LIMIT):
            raise ValueError(
                f"order type must be market or limit, got {self.type}"
            )
        if (self.type == OrderType.LIMIT) != (self.limit_price is not None):
            raise ValueError("limit_price must be set for limit orders only")


class Rule(Component):
    """Base class of rules, which turn signals into order requests.

    Subclasses inherit from SymbolRule or PortfolioRule. A rule decides for
    its strategy: a position belongs to the strategy whose rule opened it
    until it is flat again, and the runtime keeps other strategies from
    trading that symbol meanwhile. A rule that requests an order for a symbol
    that another strategy owns collides with it: the runtime deactivates the
    rule's strategy or halts the run.

    Attributes
    ----------
    signal: Signal
        The signal of the rule's strategy.

    Methods
    -------
    on_fill
        Handle a full or partial fill of one of the rule's orders.
    on_cancel
        Handle one of the rule's orders ending without a full fill.
    """

    def __init__(self, signal: Signal, **kwargs):
        """Initialize the rule.

        Parameters
        ----------
        signal: Signal
            The signal of the rule's strategy.
        """
        super().__init__(**kwargs)
        self.signal = signal

    async def on_fill(self, trade: Trade) -> None:
        """Handle a full or partial fill of one of the rule's orders.

        The runtime calls this method after it updates the position of the
        rule's strategy. The base implementation does nothing.

        Parameters
        ----------
        trade: Trade
            The execution.
        """

    async def on_cancel(self, order: Order) -> None:
        """Handle one of the rule's orders ending without a full fill.

        The runtime calls this method when an order is canceled, rejected or
        expires, including when the runtime cancels a stale order. The base
        implementation does nothing.

        Parameters
        ----------
        order: Order
            The order, with its final status.
        """


class SymbolRule(Rule):
    """Rule that decides for one symbol at a time.

    Methods
    -------
    decide
        Return the orders to submit for a symbol.
    """

    async def decide(
        self, symbol: str, now: pd.Timestamp, position: float
    ) -> list[OrderRequest]:
        """Return the orders to submit for a symbol.

        The runtime calls this method once per bar for each symbol on which
        the rule's signal fired, or in which its strategy holds a position, so
        the rule can also exit on stops, targets or the time of day. It does
        not call it while the strategy has an open order for symbol, or while
        another strategy owns symbol. The base implementation returns no
        orders.

        Read the value of the signal with self.signal.at(symbol, now), which
        is NaN unless the signal fired, or whether it fired with
        self.signal.fired(symbol, now).

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        position: float
            The strategy's position in symbol, negative when short.
        """
        return []


class PortfolioRule(Rule, _Recurring):
    """Rule that decides for all symbols of its signal at once.

    Use for rebalancing and other decisions that compare symbols. When
    trading live, a single consumer runs every portfolio rule and receives
    every symbol of their filters.

    Attributes
    ----------
    recurrence: pd.Timedelta
        The interval between decisions.
    last_run: Optional[pd.Timestamp]
        The time at which the runtime last asked the rule to decide, or None
        before the first.

    Methods
    -------
    decide
        Return the orders to submit for the rule's symbols.
    is_due
        Return whether the rule decides at a time.
    """

    recurrence: pd.Timedelta

    def __init__(self, recurrence: pd.Timedelta, **kwargs):
        """Initialize the rule.

        Parameters
        ----------
        recurrence: pd.Timedelta
            The interval between decisions.
        """
        super().__init__(recurrence=recurrence, **kwargs)

    async def decide(
        self,
        now: pd.Timestamp,
        positions: dict[str, float],
        symbols: list[str],
    ) -> list[OrderRequest]:
        """Return the orders to submit for the rule's symbols.

        The runtime submits the sell orders before the buy orders. The base
        implementation returns no orders.

        Read the values of the signal with self.signal.latest(symbols, now).

        Parameters
        ----------
        now: pd.Timestamp
            The time of the latest bar.
        positions: dict[str, float]
            The strategy's position in each symbol it holds.
        symbols: list[str]
            The symbols that the strategy's filter selected or that the
            strategy holds, sorted.
        """
        return []


@dataclass(eq=False)
class Strategy:
    """A named filter, signal and rule that the runtime runs together.

    The runtime activates and deactivates strategies as a whole, and a
    strategy owns the symbols in which its rule's orders opened positions. Its
    filter, which selects the symbols that its signal evaluates, has the name
    of the strategy, and runs in the filter process when trading live.

    Attributes
    ----------
    name: str
        The name of the strategy.
    rule: Rule
        The rule, which requests the orders of the strategy.
    filter: Optional[Filter], default None
        The filter, or None in processes that do not run filters.
    signal: Signal
        The signal of the rule, which predicts the price movements that the
        rule decides on.
    active: bool, default True
        Whether the runtime runs the strategy: asks its rule to decide,
        evaluates its signal and keeps the symbols that its filter selects,
        which a backtest also stops running. False once its rule requests a
        symbol that another strategy owns.
    """

    name: str
    rule: Rule
    filter: Optional[Filter] = None
    active: bool = True

    @property
    def signal(self) -> Signal:
        """Return the signal of the strategy's rule."""
        return self.rule.signal

    def __repr__(self):
        """Return the name of the strategy."""
        return self.name
