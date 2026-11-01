"""Strategy components: filters, indicators, signals and rules.

A trade plan wires these components into a StrategyGraph. Filters select the
symbols to trade. Indicators compute values from market data. Signals turn
indicator values into predictions of price movement for the symbols that
their filters selected. Rules turn signals and positions into order requests,
which the runtime executes: the consumer when trading live, and the backtester
otherwise. Components never submit orders themselves.

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
    Rule that decides for all symbols of its signals at once.
StrategyGraph
    The components of a trade plan and the links between them.

Functions
---------
lookback_start
    Return the start of the bars that a computation through now reads.
create_filters
    Create the filters of a trade plan.
portfolio_filters
    Return the filters that feed a portfolio rule.
select_rules
    Return a trade plan with only some of its rules.
"""

import copy
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Self, TypeVar

import pandas as pd

from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import Order, OrderType, Trade
from liualgotrader.common.utils import load_class
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
    indicators: dict[str, Indicator]
        The shared indicators, by class and parameters.
    compute_through: Optional[pd.Timestamp]
        The time through which indicators and signals compute on a cache
        miss, or None for the time asked for. The backtester sets it to the
        end of the day, so each result is computed once a day.

    Methods
    -------
    bars
        Return the bars of a symbol from a start time through now.
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
        """
        self.data_loader = data_loader
        self.trader = trader
        self.backtesting = backtesting
        self.indicators: dict[str, Indicator] = {}
        self.compute_through: Optional[pd.Timestamp] = None
        self._versions: dict[str, int] = {}
        self._shortable: dict[str, bool] = {}
        self._fetched: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

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

    Subclasses take their trade plan settings as keyword arguments and pass
    the remaining keyword arguments on to the base initializer, for example
    ``def __init__(self, window: int = 20, **kwargs)``. An unknown setting in
    the trade plan then raises TypeError instead of being ignored.

    Attributes
    ----------
    ctx: Context
        The context of the run.
    name: str
        The name of the component in the trade plan, or its class name.
    """

    def __init__(self, ctx: Context, name: Optional[str] = None):
        """Initialize the component.

        Parameters
        ----------
        ctx: Context
            The context of the run.
        name: Optional[str], default None
            The name of the component in the trade plan, or None for the class
            name.
        """
        self.ctx = ctx
        self.name = name or type(self).__name__

    def __repr__(self):
        """Return the name of the component."""
        return self.name


def lookback_start(now: pd.Timestamp, days: int) -> pd.Timestamp:
    """Return the start of the bars that a computation through now reads.

    Anchor the start to the day of now rather than to now itself, so that the
    computations of a day share their first bar. Indicator and Signal
    results then do not depend on how far they were computed, as compute
    requires.

    Parameters
    ----------
    now: pd.Timestamp
        The time of the last bar.
    days: int
        The number of calendar days before the day of now to start at.
    """
    return now.normalize() - pd.Timedelta(days=days)


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
        symbol changed since it was computed. Compute through the
        compute_through time of the context, if it is later than now.

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
            through = max(now, self.ctx.compute_through or now)
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


class Filter(Component):
    """Select the symbols that signals evaluate.

    Replaces Scanner. Subclasses implement run. Each run replaces the
    filter's universe with the symbols it selects, and the universe lasts
    until the next run, even across days.

    Attributes
    ----------
    recurrence: Optional[pd.Timedelta]
        The interval between runs, or None to run once a day.

    Methods
    -------
    run
        Return the symbols that the filter selects.
    select
        Return the symbols that run selects, in lower case.
    """

    def __init__(self, recurrence: Optional[pd.Timedelta] = None, **kwargs):
        """Initialize the filter.

        Parameters
        ----------
        recurrence: Optional[pd.Timedelta], default None
            The interval between runs, or None to run once a day.
        """
        super().__init__(**kwargs)
        self.recurrence = recurrence

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

        The runtime calls this method rather than run.

        Parameters
        ----------
        now: pd.Timestamp
            The time to select as of, which is in the past when backtesting.
        """
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
        relies on this to compute a whole day at once.

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
    the symbols selected by the filters that the trade plan links it to. It
    does not know about positions or orders.

    A signal value is a float: a positive value predicts a rise and a negative
    value a fall, and the magnitude, at most 1, is the confidence. NaN means no
    prediction. A row with a value is an event that the runtime passes to the
    rules of the signal, so a signal that holds a value on every bar makes its
    rules decide on every bar.

    Methods
    -------
    compute
        Return the signal values for a symbol through a time.
    get
        Return the cached signal values for a symbol through a time.
    at
        Return the signal value for a symbol at a time.
    """

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        """Return the signal values for a symbol through a time.

        Subclasses must override this method. The value of each row must
        depend only on data stamped at or before that row.

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

    Subclasses inherit from SymbolRule or PortfolioRule. A position belongs to
    the rule that opened it until it is flat again, and the runtime keeps
    other rules from trading that symbol meanwhile.

    Attributes
    ----------
    signals: list[Signal]
        The signals that the trade plan links to the rule.

    Methods
    -------
    on_fill
        Handle a full or partial fill of one of the rule's orders.
    on_cancel
        Handle one of the rule's orders ending without a full fill.
    """

    def __init__(self, signals: list[Signal], **kwargs):
        """Initialize the rule.

        Parameters
        ----------
        signals: list[Signal]
            The signals that the trade plan links to the rule.
        """
        super().__init__(**kwargs)
        self.signals = signals

    async def on_fill(self, trade: Trade) -> None:
        """Handle a full or partial fill of one of the rule's orders.

        The runtime calls this method after it updates the rule's position.
        The base implementation does nothing.

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
        self,
        symbol: str,
        now: pd.Timestamp,
        position: float,
        fired: dict[str, float],
    ) -> list[OrderRequest]:
        """Return the orders to submit for a symbol.

        The runtime calls this method once per bar for each symbol on which
        one of the rule's signals fired, or in which the rule holds a
        position, so the rule can also exit on stops, targets or the time of
        day. It does not call it while the rule has an open order for symbol.
        The base implementation returns no orders.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        position: float
            The rule's position in symbol, negative when short.
        fired: dict[str, float]
            The value of each of the rule's signals that fired at now, by
            signal name; empty if none did.
        """
        return []


class PortfolioRule(Rule):
    """Rule that decides for all symbols of its signals at once.

    Use for rebalancing and other decisions that compare symbols. When
    trading live, a single consumer runs every portfolio rule and receives
    every symbol of their filters.

    Attributes
    ----------
    recurrence: pd.Timedelta
        The interval between decisions.

    Methods
    -------
    decide
        Return the orders to submit for the rule's symbols.
    """

    def __init__(self, recurrence: pd.Timedelta, **kwargs):
        """Initialize the rule.

        Parameters
        ----------
        recurrence: pd.Timedelta
            The interval between decisions.
        """
        super().__init__(**kwargs)
        self.recurrence = recurrence

    async def decide(
        self,
        now: pd.Timestamp,
        positions: dict[str, float],
        signals: pd.DataFrame,
    ) -> list[OrderRequest]:
        """Return the orders to submit for the rule's symbols.

        The runtime submits the sell orders before the buy orders. The base
        implementation returns no orders.

        Parameters
        ----------
        now: pd.Timestamp
            The time of the latest bar.
        positions: dict[str, float]
            The rule's position in each symbol it holds.
        signals: pd.DataFrame
            The latest value at or before now of each of the rule's signals,
            with a row per symbol in their filters and a column per signal
            name; NaN where a signal has no value.
        """
        return []


def _links(spec: dict, key: str, targets: dict, owner: str) -> list[str]:
    """Return the names that a trade plan entry links to.

    Parameters
    ----------
    spec: dict
        The trade plan entry.
    key: str
        The setting that lists the linked names.
    targets: dict
        The trade plan section that the names must be in.
    owner: str
        The name of the entry, for error messages.

    Raises
    ------
    Raise ValueError if the list is missing or empty, or names an entry that
    is not in targets.
    """
    names = spec.get(key)
    if not names:
        raise ValueError(f"{owner} must list at least one entry in {key}")
    if unknown := set(names) - set(targets):
        raise ValueError(f"{owner} links to unknown {key}: {sorted(unknown)}")
    return list(names)


def _tradeplan_links(
    tradeplan: dict,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return the links of a trade plan without creating its components.

    Parameters
    ----------
    tradeplan: dict
        The trade plan; it is not modified.

    Returns
    -------
    Return the names of the filters of each signal and the names of the
    signals of each rule.

    Raises
    ------
    Raise ValueError if a signal or rule lists no entries, or an entry that
    does not exist.
    """
    filter_specs = tradeplan.get("filters", {})
    signal_specs = tradeplan.get("signals", {})
    signal_filters = {
        name: _links(spec, "filters", filter_specs, name)
        for name, spec in signal_specs.items()
    }
    rule_signals = {
        name: _links(spec, "signals", signal_specs, name)
        for name, spec in tradeplan.get("rules", {}).items()
    }
    return signal_filters, rule_signals


def create_filters(tradeplan: dict, ctx: Context) -> dict[str, Filter]:
    """Create the filters of a trade plan.

    Parameters
    ----------
    tradeplan: dict
        The trade plan; it is not modified.
    ctx: Context
        The context passed to each filter.

    Returns
    -------
    Return the filters by name.
    """
    filters = {}
    for name, spec in copy.deepcopy(tradeplan.get("filters", {})).items():
        filter_class = load_class(Filter, spec)
        if "recurrence" in spec:
            spec["recurrence"] = pd.Timedelta(minutes=spec["recurrence"])
        filters[name] = filter_class(ctx=ctx, name=name, **spec)
    return filters


def portfolio_filters(tradeplan: dict) -> set[str]:
    """Return the filters that feed a PortfolioRule through its signals.

    Load the rule classes without creating the rules.

    Parameters
    ----------
    tradeplan: dict
        The trade plan; it is not modified.

    Raises
    ------
    Raise the exceptions of _tradeplan_links and load_class.
    """
    signal_filters, rule_signals = _tradeplan_links(tradeplan)
    names: set[str] = set()
    for name, spec in copy.deepcopy(tradeplan.get("rules", {})).items():
        if issubclass(load_class(Rule, spec), PortfolioRule):
            for signal in rule_signals[name]:
                names.update(signal_filters[signal])
    return names


def select_rules(tradeplan: dict, rule_names: Optional[list[str]]) -> dict:
    """Return a trade plan with only some of its rules.

    Keep the signals of the selected rules, and the filters of those signals.

    Parameters
    ----------
    tradeplan: dict
        The trade plan; it is not modified.
    rule_names: Optional[list[str]]
        The rules to keep, or None or empty for all.

    Raises
    ------
    Raise ValueError if a selected rule is not in the trade plan, and the
    exceptions of _tradeplan_links.
    """
    if not rule_names:
        return tradeplan

    signal_filters, rule_signals = _tradeplan_links(tradeplan)
    if unknown := set(rule_names) - set(rule_signals):
        raise ValueError(f"unknown rules: {sorted(unknown)}")
    signal_names = {s for r in rule_names for s in rule_signals[r]}
    filter_names = {f for s in signal_names for f in signal_filters[s]}

    plan = dict(tradeplan)
    plan["rules"] = {name: tradeplan["rules"][name] for name in rule_names}
    plan["signals"] = {
        name: spec
        for name, spec in tradeplan["signals"].items()
        if name in signal_names
    }
    plan["filters"] = {
        name: spec
        for name, spec in tradeplan.get("filters", {}).items()
        if name in filter_names
    }
    return plan


@dataclass
class StrategyGraph:
    """The components of a trade plan and the links between them.

    Attributes
    ----------
    filters: dict[str, Filter]
        The filters by name; empty in processes that do not run filters.
    signals: dict[str, Signal]
        The signals by name.
    rules: dict[str, Rule]
        The rules by name.
    signal_filters: dict[str, list[str]]
        The names of the filters of each signal.
    rule_signals: dict[str, list[str]]
        The names of the signals of each rule.

    Methods
    -------
    from_tradeplan
        Create the components of a trade plan.
    signals_of_filter
        Return the signals that evaluate the symbols of a filter.
    rules_of_signal
        Return the rules that a signal fires.
    """

    filters: dict[str, Filter]
    signals: dict[str, Signal]
    rules: dict[str, Rule]
    signal_filters: dict[str, list[str]] = field(default_factory=dict)
    rule_signals: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_tradeplan(
        cls, tradeplan: dict, ctx: Context, with_filters: bool = True
    ) -> Self:
        """Create the components of a trade plan and link them.

        Parameters
        ----------
        tradeplan: dict
            The trade plan; it is not modified.
        ctx: Context
            The context passed to each component.
        with_filters: bool, default True
            Whether to create the filters, which the live trader runs in a
            separate process.

        Raises
        ------
        Raise the exceptions of _tradeplan_links and load_class.
        """
        plan = copy.deepcopy(tradeplan)
        signal_filters, rule_signals = _tradeplan_links(plan)

        signals: dict[str, Signal] = {}
        for name, spec in plan.get("signals", {}).items():
            del spec["filters"]
            signals[name] = load_class(Signal, spec)(
                ctx=ctx, name=name, **spec
            )

        rules: dict[str, Rule] = {}
        for name, spec in plan.get("rules", {}).items():
            del spec["signals"]
            rule_class = load_class(Rule, spec)
            if issubclass(rule_class, PortfolioRule) and "recurrence" in spec:
                spec["recurrence"] = pd.Timedelta(minutes=spec["recurrence"])
            rules[name] = rule_class(
                ctx=ctx,
                name=name,
                signals=[signals[s] for s in rule_signals[name]],
                **spec,
            )

        return cls(
            filters=create_filters(tradeplan, ctx) if with_filters else {},
            signals=signals,
            rules=rules,
            signal_filters=signal_filters,
            rule_signals=rule_signals,
        )

    def signals_of_filter(self, filter_name: str) -> list[Signal]:
        """Return the signals that evaluate the symbols of a filter.

        Parameters
        ----------
        filter_name: str
            The name of the filter.
        """
        return [
            self.signals[name]
            for name, filters in self.signal_filters.items()
            if filter_name in filters
        ]

    def rules_of_signal(self, signal_name: str) -> list[Rule]:
        """Return the rules that a signal fires.

        Parameters
        ----------
        signal_name: str
            The name of the signal.
        """
        return [
            self.rules[name]
            for name, signals in self.rule_signals.items()
            if signal_name in signals
        ]
