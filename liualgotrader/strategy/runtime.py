"""Run state shared by the live consumer and the backtester.

The runtime keeps one RunState per run. It tracks what the components of a
StrategyGraph do not track themselves: the universe of each filter, the
positions of each rule, the open orders, and the rule that owns each symbol.
The consumer and the backtester both decide through it, so a rule behaves the
same live and in a backtest.

Classes
-------
OpenOrder
    An order that a rule placed and that has not ended yet.
RunState
    The universes, positions, open orders and owners of a run.

Functions
---------
sells_first
    Return decisions with the sell orders before the buy orders.
"""

import logging
import math
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Optional, TypeVar

import pandas as pd

from liualgotrader.common.types import Order, Trade
from liualgotrader.strategy.new_base import (OrderRequest, PortfolioRule, Rule,
                                             StrategyGraph, SymbolRule)

logger = logging.getLogger(__name__)

A = TypeVar("A")

# A rule and an order that it requested.
Decision = tuple[Rule, OrderRequest]

# The order events that end an order without a full fill.
_END_EVENTS = (Order.EventType.canceled, Order.EventType.rejected)
_FILL_EVENTS = (Order.EventType.partial_fill, Order.EventType.fill)


@dataclass
class OpenOrder:
    """An order that a rule placed and that has not ended yet.

    Attributes
    ----------
    order: Order
        The order as submitted.
    rule: Rule
        The rule that requested the order.
    request: OrderRequest
        The request that the order executes.
    filled_qty: float
        The quantity filled so far.
    """

    order: Order
    rule: Rule
    request: OrderRequest
    filled_qty: float = 0.0


def sells_first(decisions: list[Decision]) -> list[Decision]:
    """Return decisions with the sell orders before the buy orders.

    Keep the order of decisions on the same side.

    Parameters
    ----------
    decisions: list[Decision]
        The rules and the orders they requested.
    """
    return sorted(decisions, key=lambda d: d[1].side == Order.FillSide.buy)


class RunState:
    """The universes, positions, open orders and owners of a run.

    Attributes
    ----------
    graph: StrategyGraph
        The components of the trade plan.
    universes: dict[str, set[str]]
        The symbols that each filter selected, by filter name.
    positions: dict[str, dict[str, float]]
        The open positions of each rule, by rule name and symbol; negative
        when short.
    open_orders: dict[str, OpenOrder]
        The open orders, by order ID.
    owners: dict[str, str]
        The name of the rule that owns each symbol.

    Methods
    -------
    add_symbol
        Add a symbol to the universe of a filter.
    symbols
        Return the symbols that rules may decide on.
    position
        Return the position of a rule in a symbol.
    decide_symbol
        Return the orders that the symbol rules request for a symbol.
    decide_portfolio
        Return the orders that a portfolio rule requests.
    submit
        Place the orders that rules requested and record them.
    add_open_order
        Record an order submitted for a rule.
    release_if_idle
        Release a symbol that a rule no longer trades.
    stale_orders
        Return the open orders submitted before a time.
    handle_trade
        Apply an execution report for an open order.
    fill
        Apply a fill of an open order and notify its rule.
    fill_order
        Apply a fill that the runtime observed rather than the broker.
    cancel
        Drop an open order and notify its rule.
    """

    def __init__(self, graph: StrategyGraph):
        """Initialize an empty run state.

        Parameters
        ----------
        graph: StrategyGraph
            The components of the trade plan.
        """
        self.graph = graph
        self.universes: dict[str, set[str]] = {}
        self.positions: dict[str, dict[str, float]] = {
            name: {} for name in graph.rules
        }
        self.open_orders: dict[str, OpenOrder] = {}
        self.owners: dict[str, str] = {}
        self._symbol_orders: dict[str, dict[str, OpenOrder]] = {}

    def add_symbol(self, filter_name: str, symbol: str) -> None:
        """Add a symbol to the universe of a filter.

        Parameters
        ----------
        filter_name: str
            The name of the filter that selected symbol.
        symbol: str
            The symbol.
        """
        self.universes.setdefault(filter_name, set()).add(symbol)

    def symbols(self) -> set[str]:
        """Return the symbols in a universe or owned by a rule."""
        return set(self.owners).union(*self.universes.values())

    def position(self, rule: Rule, symbol: str) -> float:
        """Return the position of a rule in a symbol, negative when short.

        Parameters
        ----------
        rule: Rule
            The rule.
        symbol: str
            The symbol.
        """
        return self.positions[rule.name].get(symbol, 0.0)

    def _signal_symbols(self, signal_name: str) -> set[str]:
        """Return the symbols that the filters of a signal selected."""
        return set().union(
            *(
                self.universes.get(filter_name, set())
                for filter_name in self.graph.signal_filters[signal_name]
            )
        )

    def _fired(self, symbol: str, now: pd.Timestamp) -> dict[str, float]:
        """Return the values of the signals that fired for a symbol at now.

        Evaluate only the signals whose filters selected symbol. Log a signal
        that raises an exception and treat it as not fired.
        """
        fired = {}
        for name, filters in self.graph.signal_filters.items():
            if not any(symbol in self.universes.get(f, ()) for f in filters):
                continue
            try:
                value = self.graph.signals[name].at(symbol, now)
            except Exception:
                logger.exception("signal %s failed on %s", name, symbol)
                continue
            if not math.isnan(value):
                fired[name] = value
        return fired

    def _latest(self, signal_name: str, symbol: str, now: pd.Timestamp):
        """Return the latest value of a signal at or before now, or NaN."""
        try:
            series = self.graph.signals[signal_name].get(symbol, now)
        except Exception:
            logger.exception("signal %s failed on %s", signal_name, symbol)
            return math.nan
        last = series.last_valid_index()
        return math.nan if last is None else float(series[last])

    def _has_open_order(self, rule: Rule, symbol: str) -> bool:
        """Return whether a rule has an open order for a symbol."""
        return any(
            o.rule is rule
            for o in self._symbol_orders.get(symbol, {}).values()
        )

    def _may_trade(self, rule: Rule, symbol: str) -> bool:
        """Return whether no other rule owns symbol and rule has no order."""
        return self.owners.get(
            symbol, rule.name
        ) == rule.name and not self._has_open_order(rule, symbol)

    def _claim(
        self, rule: Rule, requests: list[OrderRequest]
    ) -> list[Decision]:
        """Return the requests that rule may submit, and claim their symbols.

        Drop, with a warning, a request for a symbol that another rule owns or
        that rule has an open order for. Make rule the owner of the symbols of
        the other requests.
        """
        allowed = {
            r.symbol for r in requests if self._may_trade(rule, r.symbol)
        }
        decisions = []
        for request in requests:
            if request.symbol not in allowed:
                logger.warning(
                    "%s may not trade %s now, dropped %s",
                    rule,
                    request.symbol,
                    request,
                )
                continue
            self.owners[request.symbol] = rule.name
            decisions.append((rule, request))
        return decisions

    async def decide_symbol(
        self, symbol: str, now: pd.Timestamp
    ) -> list[Decision]:
        """Return the orders that the symbol rules request for a symbol.

        Ask each symbol rule that is linked to a signal that fired at now, or
        that owns symbol, unless another rule owns symbol or the rule has an
        open order for it. Pass each rule only its own fired signals. A rule
        that requests orders becomes the owner of symbol. Log a rule that
        raises an exception and skip it.

        Parameters
        ----------
        symbol: str
            The symbol of the latest bar.
        now: pd.Timestamp
            The time of the latest bar.
        """
        fired = self._fired(symbol, now)
        decisions = []
        for name, rule in self.graph.rules.items():
            if not isinstance(rule, SymbolRule):
                continue
            rule_fired = {
                s: fired[s]
                for s in self.graph.rule_signals[name]
                if s in fired
            }
            if not rule_fired and self.owners.get(symbol) != name:
                continue
            if not self._may_trade(rule, symbol):
                continue
            try:
                requests = await rule.decide(
                    symbol, now, self.position(rule, symbol), rule_fired
                )
            except Exception:
                logger.exception("rule %s failed on %s", name, symbol)
                continue
            decisions += self._claim(rule, requests)
        return decisions

    async def decide_portfolio(
        self, rule: PortfolioRule, now: pd.Timestamp
    ) -> list[Decision]:
        """Return the orders that a portfolio rule requests.

        Pass the rule the latest value at or before now of each of its
        signals, for every symbol that their filters selected or that the
        rule holds. Drop a request for a symbol that another rule owns or that
        rule has an open order for. Log an exception that the rule raises and
        return no orders.

        Parameters
        ----------
        rule: PortfolioRule
            The rule.
        now: pd.Timestamp
            The time of the latest bar.
        """
        signal_names = self.graph.rule_signals[rule.name]
        positions = dict(self.positions[rule.name])
        symbols = sorted(
            set(positions).union(*map(self._signal_symbols, signal_names))
        )
        signals = pd.DataFrame(
            {
                name: [self._latest(name, s, now) for s in symbols]
                for name in signal_names
            },
            index=pd.Index(symbols, name="symbol"),
            dtype=float,
        )
        try:
            requests = await rule.decide(now, positions, signals)
        except Exception:
            logger.exception("rule %s failed", rule)
            return []
        return self._claim(rule, requests)

    async def submit(
        self,
        decisions: list[Decision],
        place: Callable[[OrderRequest], Awaitable[Optional[Order]]],
    ) -> None:
        """Place the orders that rules requested and record them.

        Place the sell orders before the buy orders. Log an order that place
        fails to submit, and release its symbol if its rule is idle.

        Parameters
        ----------
        decisions: list[Decision]
            The rules and the orders they requested.
        place: Callable[[OrderRequest], Awaitable[Optional[Order]]]
            The function that submits an order, and returns it or None.
        """
        for rule, request in sells_first(decisions):
            order: Optional[Order] = None
            try:
                order = await place(request)
            except Exception:
                logger.exception("%s: failed to submit %s", rule, request)
            if order:
                self.add_open_order(order, rule, request)
            else:
                self.release_if_idle(rule, request.symbol)

    def add_open_order(
        self, order: Order, rule: Rule, request: OrderRequest
    ) -> None:
        """Record an order submitted for a rule.

        Parameters
        ----------
        order: Order
            The submitted order.
        rule: Rule
            The rule that requested the order.
        request: OrderRequest
            The request that the order executes.
        """
        open_order = OpenOrder(order, rule, request)
        self.open_orders[order.order_id] = open_order
        self._symbol_orders.setdefault(request.symbol, {})[
            order.order_id
        ] = open_order

    def _drop_order(self, order_id: str) -> Optional[OpenOrder]:
        """Remove an open order, and return it or None if it is not open."""
        open_order = self.open_orders.pop(order_id, None)
        if open_order is not None:
            orders = self._symbol_orders[open_order.request.symbol]
            del orders[order_id]
            if not orders:
                del self._symbol_orders[open_order.request.symbol]
        return open_order

    def release_if_idle(self, rule: Rule, symbol: str) -> None:
        """Release a symbol if rule owns it, is flat and has no open order.

        Parameters
        ----------
        rule: Rule
            The rule.
        symbol: str
            The symbol.
        """
        if (
            self.owners.get(symbol) == rule.name
            and not self.position(rule, symbol)
            and not self._has_open_order(rule, symbol)
        ):
            del self.owners[symbol]

    def stale_orders(
        self, before: pd.Timestamp, symbol: Optional[str] = None
    ) -> list[OpenOrder]:
        """Return the open orders submitted before a time.

        Parameters
        ----------
        before: pd.Timestamp
            The time.
        symbol: Optional[str], default None
            The symbol of the orders, or None for all symbols.
        """
        orders = (
            self.open_orders
            if symbol is None
            else self._symbol_orders.get(symbol, {})
        )
        return [o for o in orders.values() if o.order.submitted_at < before]

    async def handle_trade(self, trade: Trade) -> bool:
        """Apply an execution report for an open order.

        Apply fills and partial fills, and drop the order when it is
        canceled, rejected or expires. Ignore other events.

        Parameters
        ----------
        trade: Trade
            The execution report.

        Returns
        -------
        Return False if the report did not change the run state, as happens
        when another consumer submitted the order.
        """
        if trade.event in _FILL_EVENTS:
            return await self.fill(trade)
        if trade.event in _END_EVENTS:
            return await self.cancel(trade.order_id, trade.event)
        return False

    async def fill(self, trade: Trade) -> bool:
        """Apply a fill of an open order and notify its rule.

        Update the position of the rule, close the order on a full fill,
        release the symbol if the rule is now idle, then call the rule's
        on_fill.

        Parameters
        ----------
        trade: Trade
            The fill, with the quantity of this execution.

        Returns
        -------
        Return False if the order is not open in this run.
        """
        open_order = self.open_orders.get(trade.order_id)
        if open_order is None:
            return False

        rule, request = open_order.rule, open_order.request
        sign = 1 if request.side == Order.FillSide.buy else -1
        qty = round(
            self.position(rule, request.symbol) + sign * trade.filled_qty, 8
        )
        if qty:
            self.positions[rule.name][request.symbol] = qty
        else:
            self.positions[rule.name].pop(request.symbol, None)
        open_order.filled_qty += trade.filled_qty
        if trade.event == Order.EventType.fill:
            self._drop_order(trade.order_id)
        self.release_if_idle(rule, request.symbol)

        await _notify(rule.on_fill, trade)
        return True

    async def fill_order(
        self,
        open_order: OpenOrder,
        qty: float,
        price: float,
        fee: float,
        now: pd.Timestamp,
        final: bool = True,
    ) -> None:
        """Apply a fill that the runtime observed rather than the broker.

        Parameters
        ----------
        open_order: OpenOrder
            The open order.
        qty: float
            The quantity of the fill.
        price: float
            The average price of the fill.
        fee: float
            The fee of the fill.
        now: pd.Timestamp
            The time of the fill.
        final: bool, default True
            Whether the fill completes the order.
        """
        request = open_order.request
        await self.fill(
            Trade(
                order_id=open_order.order.order_id,
                symbol=request.symbol,
                event=(
                    Order.EventType.fill
                    if final
                    else Order.EventType.partial_fill
                ),
                side=request.side,
                filled_qty=qty,
                trade_fee=fee,
                filled_avg_price=price,
                liquidity="",
                updated_at=now,
            )
        )

    async def cancel(
        self,
        order_id: str,
        event: Order.EventType = Order.EventType.canceled,
    ) -> bool:
        """Drop an open order and notify its rule.

        Release the symbol if the rule is now idle, then call the rule's
        on_cancel with the order and its final status.

        Parameters
        ----------
        order_id: str
            The ID of the order.
        event: Order.EventType, default Order.EventType.canceled
            The final status of the order.

        Returns
        -------
        Return False if the order is not open in this run.
        """
        open_order = self._drop_order(order_id)
        if open_order is None:
            return False

        self.release_if_idle(open_order.rule, open_order.request.symbol)
        await _notify(
            open_order.rule.on_cancel,
            replace(
                open_order.order,
                event=event,
                filled_qty=open_order.filled_qty,
            ),
        )
        return True


async def _notify(callback: Callable[[A], Awaitable[None]], arg: A) -> None:
    """Call a rule callback, and log rather than raise its exceptions."""
    try:
        await callback(arg)
    except Exception:
        logger.exception("%s failed", callback.__qualname__)
