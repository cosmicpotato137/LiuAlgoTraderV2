"""Run state shared by the live consumer and the backtester.

The runtime keeps one RunState per run. It tracks what the strategies of a
trade plan do not track themselves: the universe of each filter, the
positions of each strategy, the open orders, and the strategy that owns each
symbol. The consumer and the backtester both decide through it, so a strategy
behaves the same live and in a backtest.

Classes
-------
OpenOrder
    An order that a strategy placed and that has not ended yet.
RunState
    The universes, positions, open orders and owners of a run.

Functions
---------
sells_first
    Return decisions with the sell orders before the buy orders.
"""

import logging
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Iterable, Optional, cast

import pandas as pd

from liualgotrader.common.exceptions import OwnershipCollision
from liualgotrader.common.types import Order, Trade
from liualgotrader.common.utils import notify
from liualgotrader.strategy.new_base import (OrderRequest, PortfolioRule,
                                             Strategy, SymbolRule)

logger = logging.getLogger(__name__)

# A strategy and an order that its rule requested.
StrategyOrderRequest = tuple[Strategy, OrderRequest]

# The order events that end an order without a full fill.
_END_EVENTS = (Order.EventType.canceled, Order.EventType.rejected)
_FILL_EVENTS = (Order.EventType.partial_fill, Order.EventType.fill)


@dataclass
class OpenOrder:
    """An order that a strategy placed and that has not ended yet.

    Attributes
    ----------
    order: Order
        The order as submitted.
    strategy: Strategy
        The strategy whose rule requested the order.
    request: OrderRequest
        The request that the order executes.
    filled_qty: float
        The quantity filled so far.
    """

    order: Order
    strategy: Strategy
    request: OrderRequest
    filled_qty: float = 0.0


def sells_first(decisions: list[StrategyOrderRequest]) -> list[StrategyOrderRequest]:
    """Return decisions with the sell orders before the buy orders.

    Keep the order of decisions on the same side.

    Parameters
    ----------
    decisions: list[Decision]
        The strategies and the orders that their rules requested.
    """
    return sorted(decisions, key=lambda d: d[1].side == Order.FillSide.buy)


class RunState:
    """The universes, positions, open orders and owners of a run.

    Attributes
    ----------
    strategies: dict[str, Strategy]
        The strategies of the trade plan, by name.
    universes: dict[str, set[str]]
        The symbols that the filter of each strategy selected, by strategy
        name, which is also the name of the filter.
    positions: dict[str, dict[str, float]]
        The open positions of each strategy, by strategy name and symbol;
        negative when short.
    open_orders: dict[str, OpenOrder]
        The open orders, by order ID.
    symbol_owners: dict[str, str]
        The name of the strategy that owns each symbol.
    halt_on_collision: bool
        Whether a strategy that requests a symbol another strategy owns raises
        OwnershipCollision, rather than being deactivated with a warning.

    Methods
    -------
    set_universe
        Replace the universe of a strategy.
    symbols
        Return the symbols that strategies may decide on.
    position
        Return the position of a strategy in a symbol.
    decide_symbol
        Return the orders that the symbol rules request for a symbol.
    decide_portfolio
        Return the orders that the portfolio rule of a strategy requests.
    submit
        Place the orders that strategies requested and record them.
    add_open_order
        Record an order submitted for a strategy.
    release_if_idle
        Release a symbol that a strategy no longer trades.
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

    def __init__(
        self, strategies: dict[str, Strategy], halt_on_collision: bool = False
    ):
        """Initialize an empty run state.

        Parameters
        ----------
        strategies: dict[str, Strategy]
            The strategies of the trade plan, by name.
        halt_on_collision: bool, default False
            Whether a strategy that requests a symbol another strategy owns
            raises OwnershipCollision, rather than being deactivated with a
            warning.
        """
        self.strategies = strategies
        self.universes: dict[str, set[str]] = {}
        self.positions: dict[str, dict[str, float]] = {
            name: {} for name in strategies
        }
        self.open_orders: dict[str, OpenOrder] = {}
        self.symbol_owners: dict[str, str] = {}
        self.halt_on_collision = halt_on_collision
        self._symbol_orders: dict[str, dict[str, OpenOrder]] = {} # TODO: open_orders: dict[str, OpenOrder] should be a field in Strategy

    def set_universe(self, name: str, symbols: Iterable[str]) -> None:
        """Replace the universe of a strategy with the symbols that its
        filter selected.

        Ignore an inactive strategy, whose universe nothing reads.

        Parameters
        ----------
        name: str
            The name of the strategy, which is also the name of its filter.
        symbols: Iterable[str]
            The symbols.
        """
        strategy = self.strategies.get(name)
        if strategy is None or strategy.active:
            self.universes[name] = set(symbols)

    def symbols(self) -> set[str]:
        """Return the symbols in a universe or owned by a strategy."""
        return set(self.symbol_owners).union(*self.universes.values())

    def position(self, strategy: Strategy, symbol: str) -> float:
        """Return the position of a strategy in a symbol, negative when short.

        Parameters
        ----------
        strategy: Strategy
            The strategy.
        symbol: str
            The symbol.
        """
        return self.positions[strategy.name].get(symbol, 0.0)

    def _universe(self, strategy: Strategy) -> set[str]: # TODO: short function, can be inlined
        """Return the symbols that the filter of a strategy selected."""
        return self.universes.get(strategy.name, set())

    def _fired(
        self, strategy: Strategy, symbol: str, now: pd.Timestamp
    ) -> bool: # TODO: short function, can be inlined
        """Return whether a strategy's signal fired at now on a symbol that
        the strategy's filter selected.

        Evaluate the signal only for such a symbol.
        """
        return symbol in self._universe(strategy) and strategy.signal.fired(
            symbol, now
        )

    def _has_open_order(self, strategy: Strategy, symbol: str) -> bool:
        """Return whether a strategy has an open order for a symbol."""
        return any(
            o.strategy is strategy
            for o in self._symbol_orders.get(symbol, {}).values()
        )

    def _claim(
        self, strategy: Strategy, requests: list[OrderRequest]
    ) -> list[StrategyOrderRequest]:
        """Return the requests that strategy may submit, and claim their
        symbols.

        Raises
        ------
        Raise OwnershipCollision if strategy collides and halt_on_collision is
        set.
        """
        for request in requests:
            owner = self.symbol_owners.get(request.symbol, strategy.name)
            if owner == strategy.name:
                continue
            collision = OwnershipCollision(
                strategy.name, request.symbol, owner
            )
            if self.halt_on_collision:
                raise collision
            strategy.active = False
            self.universes.pop(strategy.name, None)
            logger.warning(
                "%s: deactivated %s, dropped its requests %s, and left its "
                "positions %s to no strategy",
                collision,
                strategy,
                requests,
                self.positions[strategy.name],
            )
            return []

        decisions = []
        for request in requests:
            if self._has_open_order(strategy, request.symbol):
                logger.warning(
                    "%s has an open order for %s, dropped %s",
                    strategy,
                    request.symbol,
                    request,
                )
                continue
            self.symbol_owners[request.symbol] = strategy.name
            decisions.append((strategy, request))
        return decisions

    async def decide_symbol(
        self, symbol: str, now: pd.Timestamp
    ) -> list[StrategyOrderRequest]:
        """Return the orders that the symbol rules of the active strategies
        request for a symbol.

        Parameters
        ----------
        symbol: str
            The symbol of the latest bar.
        now: pd.Timestamp
            The time of the latest bar.

        Raises
        ------
        Raise OwnershipCollision if a strategy requests a symbol that another
        strategy owns and halt_on_collision is set.
        """
        decisions = []
        for strategy in self.strategies.values():
            rule = strategy.rule
            if not (
                isinstance(rule, SymbolRule)
                and strategy.active
                and self.symbol_owners.get(symbol) in (None, strategy.name)
                and not self._has_open_order(strategy, symbol)
            ):
                continue
            if (
                symbol not in self.symbol_owners
                and not self._fired(strategy, symbol, now)
            ):
                continue
            try:
                requests = await rule.decide(
                    symbol, now, self.position(strategy, symbol)
                )
            except Exception:
                logger.exception("rule %s failed on %s", rule, symbol)
                continue
            decisions += self._claim(strategy, requests)
        return decisions

    async def decide_portfolio(
        self, strategy: Strategy, now: pd.Timestamp
    ) -> list[StrategyOrderRequest]:
        """Return the orders that the portfolio rule of a strategy requests.

        Return no orders if the strategy is inactive. Otherwise record now as
        the last run of the rule, and pass the rule every symbol that the
        strategy's filter selected or that it holds. Deactivate the strategy
        if the rule requests a symbol that another strategy owns, and drop a
        request for a symbol that the strategy has an open order for, as
        _claim does. Log an exception that the rule raises and return no
        orders.

        Parameters
        ----------
        strategy: Strategy
            The strategy, whose rule is a PortfolioRule.
        now: pd.Timestamp
            The time of the latest bar.

        Raises
        ------
        Raise OwnershipCollision if the rule requests a symbol that another
        strategy owns and halt_on_collision is set.
        """
        if not strategy.active:
            return []
        rule = cast(PortfolioRule, strategy.rule)
        rule.last_run = now
        positions = dict(self.positions[strategy.name])
        symbols = sorted(set(positions) | self._universe(strategy))
        try:
            requests = await rule.decide(now, positions, symbols)
        except Exception:
            logger.exception("rule %s failed", rule)
            return []
        return self._claim(strategy, requests)

    async def submit(
        self,
        decisions: list[StrategyOrderRequest],
        place: Callable[[OrderRequest], Awaitable[Optional[Order]]],
    ) -> None:
        """Place the orders that strategies requested and record them.

        Place the sell orders before the buy orders. Log an order that place
        fails to submit, and release its symbol if its strategy is idle.

        Parameters
        ----------
        decisions: list[Decision]
            The strategies and the orders that their rules requested.
        place: Callable[[OrderRequest], Awaitable[Optional[Order]]]
            The function that submits an order, and returns it or None.
        """
        for strategy, request in sells_first(decisions):
            order: Optional[Order] = None
            try:
                order = await place(request)
            except Exception:
                logger.exception("%s: failed to submit %s", strategy, request)
            if order:
                self.add_open_order(order, strategy, request)
            else:
                self.release_if_idle(strategy, request.symbol)

    def add_open_order(
        self, order: Order, strategy: Strategy, request: OrderRequest
    ) -> None:
        """Record an order submitted for a strategy.

        Parameters
        ----------
        order: Order
            The submitted order.
        strategy: Strategy
            The strategy whose rule requested the order.
        request: OrderRequest
            The request that the order executes.
        """
        open_order = OpenOrder(order, strategy, request)
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

    def release_if_idle(self, strategy: Strategy, symbol: str) -> None:
        """Release a symbol if strategy owns it, is flat and has no open
        order.

        Parameters
        ----------
        strategy: Strategy
            The strategy.
        symbol: str
            The symbol.
        """
        if (
            self.symbol_owners.get(symbol) == strategy.name
            and not self.position(strategy, symbol)
            and not self._has_open_order(strategy, symbol)
        ):
            del self.symbol_owners[symbol]

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

        Update the position of the strategy, close the order on a full fill,
        release the symbol if the strategy is now idle, then call the rule's
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

        strategy, request = open_order.strategy, open_order.request
        sign = 1 if request.side == Order.FillSide.buy else -1
        qty = round(
            self.position(strategy, request.symbol) + sign * trade.filled_qty,
            8,
        )
        if qty:
            self.positions[strategy.name][request.symbol] = qty
        else:
            self.positions[strategy.name].pop(request.symbol, None)
        open_order.filled_qty += trade.filled_qty
        if trade.event == Order.EventType.fill:
            self._drop_order(trade.order_id)
        self.release_if_idle(strategy, request.symbol)

        await notify(strategy.rule.on_fill, trade)
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

        Release the symbol if the strategy is now idle, then call the rule's
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

        self.release_if_idle(open_order.strategy, open_order.request.symbol)
        await notify(
            open_order.strategy.rule.on_cancel,
            replace(
                open_order.order,
                event=event,
                filled_qty=open_order.filled_qty,
            ),
        )
        return True
