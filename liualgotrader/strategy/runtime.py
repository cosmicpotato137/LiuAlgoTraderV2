"""Run state shared by the live consumer and the backtester.

Classes
-------
RunState
    The strategies, open orders and symbol owners of a run.
"""

import logging
from dataclasses import replace
from typing import Awaitable, Callable, Iterable, Optional, cast

import pandas as pd

from liualgotrader.common.exceptions import OwnershipCollision
from liualgotrader.common.types import Order, Trade
from liualgotrader.common.utils import notify
from liualgotrader.strategy.base import (OpenOrder, OrderRequest,
                                             PortfolioRule, Strategy,
                                             SymbolRule)

logger = logging.getLogger(__name__)

# A strategy and an order that its rule requested.
StrategyOrderRequest = tuple[Strategy, OrderRequest]

# The order events that end an order without a full fill.
_END_EVENTS = (Order.EventType.canceled, Order.EventType.rejected)
_FILL_EVENTS = (Order.EventType.partial_fill, Order.EventType.fill)


class RunState:
    """The strategies, open orders and symbol owners of a run.

    Attributes
    ----------
    strategies: dict[str, Strategy]
        The strategies of the trade plan, by name, whose universes,
        positions and open orders the run state updates.
    symbol_owners: dict[str, str]
        The name of the strategy that owns each symbol.
    halt_on_collision: bool
        Whether a strategy that requests a symbol another strategy owns raises
        OwnershipCollision, rather than being deactivated with a warning.

    Methods
    -------
    set_universe
        Replace the universe of a strategy.
    get_open_orders_by_id
        Return the open orders of all strategies, by order ID.
    get_all_symbols
        Return the symbols that strategies may decide on.
    decide_symbol
        Return the orders that the symbol rules request for a symbol.
    decide_portfolio
        Return the orders that the portfolio rule of a strategy requests.
    submit_order
        Place the orders that strategies requested and record them.
    get_stale_orders
        Return the open orders submitted before a time.
    handle_trade
        Apply an execution report for an open order.
    fill_order
        Apply a fill that the runtime observed rather than the broker.
    cancel_order
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
        self.symbol_owners: dict[str, str] = {}
        self.halt_on_collision = halt_on_collision

    def get_open_orders_by_id(self) -> dict[str, OpenOrder]:
        """Return the open orders of all strategies, by order ID."""
        return {
            order_id: open_order
            for strategy in self.strategies.values()
            for order_id, open_order in strategy.open_orders.items()
        }

    def set_universe(self, name: str, symbols: Iterable[str]) -> None:
        """Replace the universe of a strategy with the symbols that its
        filter selected.

        Parameters
        ----------
        name: str
            The name of the strategy, which is also the name of its filter.
        symbols: Iterable[str]
            The symbols.
        """
        strategy = self.strategies.get(name)
        if strategy is not None and strategy.active:
            strategy.universe = set(symbols)

    def get_all_symbols(self) -> set[str]:
        """Return the symbols in a universe or owned by a strategy."""
        return set(self.symbol_owners).union(
            *(strategy.universe for strategy in self.strategies.values())
        )

    def _has_open_order(self, strategy: Strategy, symbol: str) -> bool:
        """Return whether a strategy has an open order for a symbol."""
        return any(
            o.request.symbol == symbol for o in strategy.open_orders.values()
        )

    def _create_symbol_claims(
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
            strategy.universe.clear()
            logger.warning(
                "%s: deactivated %s, dropped its requests %s, and left its "
                "positions %s to no strategy",
                collision,
                strategy,
                requests,
                strategy.positions,
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
            # Evaluate the signal only on a symbol that the strategy's filter
            # selected.
            if symbol not in self.symbol_owners and not (
                symbol in strategy.universe
                and strategy.signal.fired(symbol, now)
            ):
                continue
            try:
                requests = await rule.decide(
                    symbol, now, strategy.positions.get(symbol, 0.0)
                )
            except Exception:
                logger.exception("rule %s failed on %s", rule, symbol)
                continue
            decisions += self._create_symbol_claims(strategy, requests)
        return decisions

    async def decide_portfolio(
        self, strategy: Strategy, now: pd.Timestamp
    ) -> list[StrategyOrderRequest]:
        """Return the orders that the portfolio rule of a strategy requests.

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
        positions = dict(strategy.positions)
        symbols = sorted(set(positions) | strategy.universe)
        try:
            requests = await rule.decide(now, positions, symbols)
        except Exception:
            logger.exception("rule %s failed", rule)
            return []
        return self._create_symbol_claims(strategy, requests)

    async def submit_order(
        self,
        decisions: list[StrategyOrderRequest],
        submit_callback: Callable[[OrderRequest], Awaitable[Optional[Order]]],
    ) -> None:
        """Place the orders that strategies requested and record them.

        Parameters
        ----------
        decisions: list[StrategyOrderRequest]
            The strategies and the orders that their rules requested.
        submit_callback: Callable[[OrderRequest], Awaitable[Optional[Order]]]
            The function that submits an order, and returns it or None.
        """
        for strategy, request in sorted(
            decisions, key=lambda d: d[1].side == Order.FillSide.buy
        ):
            order: Optional[Order] = None
            try:
                order = await submit_callback(request)
            except Exception:
                logger.exception("%s: failed to submit %s", strategy, request)
            if order:
                strategy.open_orders[order.order_id] = OpenOrder(
                    order, strategy, request
                )
            else:
                self._release_if_idle(strategy, request.symbol)

    def _drop_order(self, order_id: str) -> Optional[OpenOrder]:
        """Remove an open order, and return it or None if it is not open."""
        open_order = self.get_open_orders_by_id().get(order_id)
        if open_order is not None:
            del open_order.strategy.open_orders[order_id]
        return open_order

    def _release_if_idle(self, strategy: Strategy, symbol: str) -> None:
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
            and not strategy.positions.get(symbol)
            and not self._has_open_order(strategy, symbol)
        ):
            del self.symbol_owners[symbol]

    def get_stale_orders(
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
        return [
            o
            for o in self.get_open_orders_by_id().values()
            if (symbol is None or o.request.symbol == symbol)
            and o.order.submitted_at < before
        ]

    async def handle_trade(self, trade: Trade) -> bool:
        """Apply an execution report for an open order.

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
            return await self._fill_and_notify(trade)
        if trade.event in _END_EVENTS:
            return await self.cancel_order(trade.order_id, trade.event)
        return False

    async def _fill_and_notify(self, trade: Trade) -> bool:
        """Apply a fill of an open order and notify its rule.

        Parameters
        ----------
        trade: Trade
            The fill, with the quantity of this execution.

        Returns
        -------
        Return False if the order is not open in this run.
        """
        open_order = self.get_open_orders_by_id().get(trade.order_id)
        if open_order is None:
            return False

        strategy, request = open_order.strategy, open_order.request
        sign = 1 if request.side == Order.FillSide.buy else -1
        positions = strategy.positions
        qty = round(
            positions.get(request.symbol, 0.0) + sign * trade.filled_qty, 8
        )
        if qty:
            positions[request.symbol] = qty
        else:
            positions.pop(request.symbol, None)
        open_order.filled_qty += trade.filled_qty
        if trade.event == Order.EventType.fill:
            self._drop_order(trade.order_id)
        self._release_if_idle(strategy, request.symbol)

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
        await self._fill_and_notify(
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

    async def cancel_order(
        self,
        order_id: str,
        event: Order.EventType = Order.EventType.canceled,
    ) -> bool:
        """Drop an open order and notify its rule.

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

        self._release_if_idle(open_order.strategy, open_order.request.symbol)
        await notify(
            open_order.strategy.rule.on_cancel,
            replace(
                open_order.order,
                event=event,
                filled_qty=open_order.filled_qty,
            ),
        )
        return True
