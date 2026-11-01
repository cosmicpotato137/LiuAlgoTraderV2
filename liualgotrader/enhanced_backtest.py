"""Backtest the filters, signals and rules of a trade plan on past data.

Classes
-------
Backtest
    A backtesting session: its run state, simulated orders and fills.

Functions
---------
net_cash_flow
    Return the sell value minus the buy value and fees of some trades.
write_results
    Write the trades and the summary of a session to files.
backtest_main
    Prepare and run a complete backtesting session.
backtest
    Run a backtesting session and return its batch identifier.
"""

import itertools
import logging
import uuid
from datetime import date, time
from typing import Dict, Iterator, List, Optional, Tuple, cast

import pandas as pd
from alpaca.trading.models import Calendar
from alpaca.trading.requests import GetCalendarRequest

from liualgotrader.common import clock, config
from liualgotrader.common.concurrency import reset_event_loop
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import AssetType, Order, OrderType, TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.new_base import (Component, Context, Filter,
                                             OrderRequest, PortfolioRule,
                                             StrategyGraph, select_rules)
from liualgotrader.strategy.runtime import OpenOrder, RunState
from liualgotrader.trade.factory import trader_factory
from liualgotrader.vendors.alpaca.data import AlpacaData

logger = logging.getLogger(__name__)

# The columns of the trades of a session.
TRADE_COLUMNS = ["time", "rule", "symbol", "side", "qty", "price", "fee"]


def _trading_sessions(
    from_date: date, to_date: date, asset_type: AssetType
) -> Iterator[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Yield the start and end of each trading day in a date range.

    A US equities day spans the market hours of the Alpaca market calendar,
    and a crypto day spans the whole of every calendar day, both in New York
    time.

    Parameters
    ----------
    from_date: date
        The first day of the range.
    to_date: date
        The last day of the range.
    asset_type: AssetType
        The type of asset traded.

    Raises
    ------
    Raise AssertionError for any other asset type.
    """
    if asset_type == AssetType.US_EQUITIES:
        calendar = cast(
            List[Calendar],
            AlpacaData(config.alpaca).trading_client.get_calendar(
                GetCalendarRequest(start=from_date, end=to_date)
            ),
        )
        for day in calendar:
            # Calendar.open and Calendar.close are naive New York times
            yield (
                pd.Timestamp(day.open).tz_localize(clock.NY),
                pd.Timestamp(day.close).tz_localize(clock.NY),
            )
    elif asset_type == AssetType.CRYPTO:
        for day in pd.date_range(from_date, to_date):
            yield (
                pd.Timestamp(day.date(), tz=clock.NY),
                pd.Timestamp.combine(day.date(), time.max).tz_localize(
                    clock.NY
                ),
            )
    else:
        raise AssertionError(f"Asset type {asset_type} not supported yet")


class Backtest:
    """A backtesting session: its run state, simulated orders and fills.

    Each step of a day runs at the time of a bar. A step fills the orders of
    the previous step at the open of its bar, runs the filters that are due,
    then asks the rules for orders exactly as the live consumer does.

    Attributes
    ----------
    ctx: Context
        The context of the session.
    state: RunState
        The universes, positions, open orders and owners of the session.
    scale: TimeScale
        The time between steps.
    buy_fee_percentage: float
        The buy fee, as a percentage of the trade value.
    sell_fee_percentage: float
        The sell fee, as a percentage of the trade value.
    trades: List[Dict]
        The fills, with the fields of TRADE_COLUMNS.

    Methods
    -------
    run
        Simulate every trading day in a date range.
    run_day
        Simulate a trading day.
    step
        Simulate one step of a day.
    """

    def __init__(
        self,
        ctx: Context,
        graph: StrategyGraph,
        scale: TimeScale,
        buy_fee_percentage: float = 0.0,
        sell_fee_percentage: float = 0.0,
    ):
        """Initialize a session with no positions or orders.

        Parameters
        ----------
        ctx: Context
            The context of the session, with backtesting set.
        graph: StrategyGraph
            The components of the trade plan.
        scale: TimeScale
            The time between steps.
        buy_fee_percentage: float, default 0.0
            The buy fee, as a percentage of the trade value.
        sell_fee_percentage: float, default 0.0
            The sell fee, as a percentage of the trade value.
        """
        self.ctx = ctx
        self.state = RunState(graph)
        self.scale = scale
        self.buy_fee_percentage = buy_fee_percentage
        self.sell_fee_percentage = sell_fee_percentage
        self.trades: List[Dict] = []
        self._order_ids = itertools.count(1)
        self._last_run: Dict[Component, pd.Timestamp] = {}

    def _steps(
        self, day_start: pd.Timestamp, day_end: pd.Timestamp
    ) -> pd.DatetimeIndex:
        """Return the bar times of a day: one per minute, or one per day."""
        if self.scale == TimeScale.day:
            return pd.DatetimeIndex([day_start.normalize()])
        return pd.date_range(
            day_start, day_end, freq=f"{self.scale.value}s", inclusive="left"
        )

    def _due(
        self, component: Filter | PortfolioRule, now: pd.Timestamp
    ) -> bool:
        """Return whether a filter or rule runs at now, and record it if so.

        A filter without a recurrence runs once a day.
        """
        last = self._last_run.get(component)
        recurrence = component.recurrence
        due = (
            last is None
            or (recurrence is None and last.date() != now.date())
            or (recurrence is not None and now - last >= recurrence)
        )
        if due:
            self._last_run[component] = now
        return due

    async def run(
        self, from_date: date, to_date: date, asset_type: AssetType
    ) -> None:
        """Simulate every trading day in a date range.

        Parameters
        ----------
        from_date: date
            The first day of the range.
        to_date: date
            The last day of the range.
        asset_type: AssetType
            The type of asset traded.
        """
        for day_start, day_end in _trading_sessions(
            from_date, to_date, asset_type
        ):
            await self.run_day(day_start, day_end)

    async def run_day(
        self, day_start: pd.Timestamp, day_end: pd.Timestamp
    ) -> None:
        """Simulate a trading day.

        Start with empty filter universes, so that only the rules' own
        symbols carry over from the previous day. Compute indicators and
        signals through the end of the day on first use, which their causal
        compute allows, so that later steps read them from the cache. With
        minute steps, cancel the orders still open at the end of the day, as
        day orders expire at the close; with daily steps, they fill at the
        next day's open.

        Parameters
        ----------
        day_start: pd.Timestamp
            The start of the day.
        day_end: pd.Timestamp
            The end of the day.
        """
        self.state.universes.clear()
        self.ctx.compute_through = day_end
        for now in self._steps(day_start, day_end):
            await self.step(now)
        if self.scale != TimeScale.day:
            for order_id in list(self.state.open_orders):
                await self.state.cancel(order_id)

    async def step(self, now: pd.Timestamp) -> None:
        """Simulate the step of a day at the time of a bar.

        Fill the orders of the previous step and run the filters that are
        due. Then ask the symbol rules for orders on every symbol in a
        universe or owned by a rule, and the portfolio rules whose recurrence
        elapsed, and place the orders, sells before buys.

        Parameters
        ----------
        now: pd.Timestamp
            The time of the bar.
        """
        await self._fill_open_orders(now)

        for name, selector in self.state.graph.filters.items():
            if self._due(selector, now):
                for symbol in await selector.select(now):
                    self.state.add_symbol(name, symbol)

        decisions = []
        for symbol in sorted(self.state.symbols()):
            decisions += await self.state.decide_symbol(symbol, now)
        for rule in self.state.graph.rules.values():
            if isinstance(rule, PortfolioRule) and self._due(rule, now):
                decisions += await self.state.decide_portfolio(rule, now)

        async def place(request: OrderRequest) -> Order:
            return Order(
                order_id=str(next(self._order_ids)),
                symbol=request.symbol,
                event=Order.EventType.open,
                submitted_at=now,
                price=request.limit_price,
                side=request.side,
            )

        await self.state.submit(decisions, place)

    async def _fill_open_orders(self, now: pd.Timestamp) -> None:
        """Fill the open orders at the open of the bar at now.

        Leave an order open while its symbol has no bar at now. Cancel a limit
        order that the bar does not trade through.
        """
        for order_id, open_order in list(self.state.open_orders.items()):
            bars = self.ctx.bars(open_order.request.symbol, now, now)
            if bars.empty:
                continue
            price = _execution_price(open_order.request, bars.iloc[-1])
            if price is None:
                await self.state.cancel(order_id)
            else:
                await self._fill(open_order, price, now)

    async def _fill(
        self, open_order: OpenOrder, price: float, now: pd.Timestamp
    ) -> None:
        """Fill an open order completely at a price, and record the trade."""
        request = open_order.request
        is_buy = request.side == Order.FillSide.buy
        fee = (
            price
            * request.qty
            * (self.buy_fee_percentage if is_buy else self.sell_fee_percentage)
            / 100.0
        )
        self.trades.append(
            {
                "time": now,
                "rule": open_order.rule.name,
                "symbol": request.symbol,
                "side": request.side.name,
                "qty": request.qty,
                "price": price,
                "fee": fee,
            }
        )
        await self.state.fill_order(open_order, request.qty, price, fee, now)


def _execution_price(request: OrderRequest, bar: pd.Series) -> Optional[float]:
    """Return the price at which a bar fills an order, or None.

    Fill a market order at the open. Fill a limit order at the open if the
    open is at or better than the limit, at the limit if the bar trades
    through it later, and not at all otherwise.
    """
    if request.type == OrderType.MARKET:
        return float(bar["open"])
    limit = float(request.limit_price)  # type: ignore
    if request.side == Order.FillSide.buy:
        return min(float(bar["open"]), limit) if bar["low"] <= limit else None
    return max(float(bar["open"]), limit) if bar["high"] >= limit else None


def write_results(
    batch_id: str, trades: pd.DataFrame, positions: Dict[str, Dict]
) -> None:
    """Write the trades and the summary of a session to files.

    Write the trades to <batch_id>-trades.csv, and the net cash flow, the
    number of trades and the open positions of each rule to
    <batch_id>-summary.txt, both in the current directory.

    Parameters
    ----------
    batch_id: str
        The batch identifier of the session.
    trades: pd.DataFrame
        The trades, with the columns of TRADE_COLUMNS.
    positions: Dict[str, Dict]
        The open positions of each rule, by rule name and symbol.
    """
    trades.to_csv(f"{batch_id}-trades.csv", index=False)

    lines = [f"batch-id: {batch_id}"]
    for rule, rule_positions in positions.items():
        rule_trades = trades[trades.rule == rule]
        lines += [
            f"rule {rule}:",
            f"  net cash flow: {net_cash_flow(rule_trades):.2f}",
            f"  trades: {len(rule_trades)}",
            f"  open positions: {rule_positions}",
        ]
    with open(f"{batch_id}-summary.txt", "w") as summary:
        summary.write("\n".join(lines) + "\n")


def net_cash_flow(trades: pd.DataFrame) -> float:
    """Return the sell value minus the buy value and fees of some trades.

    Parameters
    ----------
    trades: pd.DataFrame
        The trades, with the columns of TRADE_COLUMNS.
    """
    value = trades.price * trades.qty
    return float(
        value[trades.side == "sell"].sum()
        - value[trades.side == "buy"].sum()
        - trades.fee.sum()
    )


async def backtest_main(
    uid: str,
    from_date: date,
    to_date: date,
    scale: TimeScale,
    tradeplan: Dict,
    buy_fee_percentage: float,
    sell_fee_percentage: float,
    asset_type: AssetType,
    rules: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Prepare and run a complete backtesting session.

    Connect to the database, which the momentum filter reads, and create the
    components of the trade plan with a context of their own. Write the
    results with write_results.

    Parameters
    ----------
    uid: str
        The batch identifier of the session.
    from_date: date
        The first day to backtest.
    to_date: date
        The last day to backtest.
    scale: TimeScale
        The time scale of the simulation.
    tradeplan: Dict
        The trade plan.
    buy_fee_percentage: float
        The buy fee, as a percentage of the trade value.
    sell_fee_percentage: float
        The sell fee, as a percentage of the trade value.
    asset_type: AssetType
        The type of asset traded.
    rules: Optional[List[str]], default None
        The names of the rules to backtest, with their signals and filters,
        or None for all.

    Returns
    -------
    Return the trades, with the columns of TRADE_COLUMNS.
    """
    logger.info(
        "Starting back-test from %s to %s with time scale %s",
        from_date,
        to_date,
        scale,
    )
    if rules:
        logger.info("with rules:%s", rules)

    await create_db_connection()

    ctx = Context(DataLoader(scale), trader_factory(), backtesting=True)
    graph = StrategyGraph.from_tradeplan(select_rules(tradeplan, rules), ctx)
    logger.info(
        "filters %s, signals %s, rules %s",
        list(graph.filters),
        list(graph.signals),
        list(graph.rules),
    )

    session = Backtest(
        ctx, graph, scale, buy_fee_percentage, sell_fee_percentage
    )
    await session.run(from_date, to_date, asset_type)

    trades = pd.DataFrame(session.trades, columns=TRADE_COLUMNS)
    write_results(uid, trades, session.state.positions)
    return trades


def backtest(
    from_date: date,
    to_date: date,
    scale: TimeScale,
    config: Dict,
    rules: Optional[List[str]],
    asset_type: AssetType,
    buy_fee_percentage: float,
    sell_fee_percentage: float,
) -> str:
    """Run a backtesting session and return its batch identifier.

    Do not call from a coroutine. Log, rather than raise, any error or keyboard
    interrupt, and log the batch identifier in all cases.

    Parameters
    ----------
    from_date: date
        The first day to backtest.
    to_date: date
        The last day to backtest.
    scale: TimeScale
        The time scale of the simulation.
    config: Dict
        The trade plan.
    rules: Optional[List[str]]
        The names of the rules to backtest, or None for all.
    asset_type: AssetType
        The type of asset traded.
    buy_fee_percentage: float
        The buy fee, as a percentage of the trade value.
    sell_fee_percentage: float
        The sell fee, as a percentage of the trade value.
    """
    uid = str(uuid.uuid4())
    try:
        loop = reset_event_loop()
        loop.run_until_complete(
            backtest_main(
                uid,
                from_date,
                to_date,
                scale,
                config,
                buy_fee_percentage,
                sell_fee_percentage,
                asset_type,
                rules,
            )
        )
    except KeyboardInterrupt:
        logger.info("backtest() - Caught KeyboardInterrupt")
    except Exception as e:
        logger.exception(
            "backtest() - exception of type %s with args %s",
            type(e).__name__,
            e.args,
        )
    finally:
        logger.info("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=")
        logger.info("new batch-id: %s", uid)

    return uid
