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
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from liualgotrader.common import config
from liualgotrader.common.concurrency import reset_event_loop
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import AssetType, Order, OrderType, TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.new_base import (Context, OrderRequest,
                                             PortfolioRule)
from liualgotrader.strategy.runtime import OpenOrder, RunState
from liualgotrader.strategy.tradeplan import create_strategies
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)

# The columns of the trades of a session.
TRADE_COLUMNS = ["time", "strategy", "symbol", "side", "qty", "price", "fee"]


class Backtest:
    """A backtesting session: its run state, simulated orders and fills.

    Each step of a day runs at the time of a bar. A step fills the orders of
    the previous step at the open of its bar, runs the filters that are due,
    then asks the rules of the strategies for orders exactly as the live
    consumer does.

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
    simulate_range
        Simulate every trading day in a date range.
    simulate_day
        Simulate a trading day.
    simulate_timestep
        Simulate one step of a day.
    """

    def __init__(
        self,
        ctx: Context,
        state: RunState,
        scale: TimeScale,
        buy_fee_percentage: float = 0.0,
        sell_fee_percentage: float = 0.0,
    ):
        """Initialize a session with no trades.

        Parameters
        ----------
        ctx: Context
            The context of the session, with backtesting set.
        state: RunState
            The run state of the session, with the components of the trade
            plan.
        scale: TimeScale
            The time between steps.
        buy_fee_percentage: float, default 0.0
            The buy fee, as a percentage of the trade value.
        sell_fee_percentage: float, default 0.0
            The sell fee, as a percentage of the trade value.
        """
        self.ctx = ctx
        self.state = state
        self.scale = scale
        self.buy_fee_percentage = buy_fee_percentage
        self.sell_fee_percentage = sell_fee_percentage
        self.trades: List[Dict] = []
        self._order_ids = itertools.count(1)

    async def simulate_range(self, from_date: date, to_date: date) -> None:
        """Simulate every trading day in a date range.

        Take the trading days from the market calendar of the context.

        Parameters
        ----------
        from_date: date
            The first day of the range.
        to_date: date
            The last day of the range.
        """
        for day_start, day_end in self.ctx.calendar.trading_days(
            from_date, to_date
        ):
            await self.simulate_day(day_start, day_end)

    async def simulate_day(
        self, day_start: pd.Timestamp, day_end: pd.Timestamp
    ) -> None:
        """Simulate a trading day.

        Make the whole day's bars available at its start, so that each
        indicator and signal is computed once a day and later steps read it
        from the cache. Step once per bar: once at midnight on the day scale,
        and at each bar time from the start of the day otherwise.

        Parameters
        ----------
        day_start: pd.Timestamp
            The start of the day.
        day_end: pd.Timestamp
            The end of the day.
        """
        self.ctx.set_horizon(day_end)
        if self.scale == TimeScale.day:
            steps = pd.DatetimeIndex([day_start.normalize()])
        else:
            steps = pd.date_range(
                day_start,
                day_end,
                freq=f"{self.scale.value}s",
                inclusive="left",
            )
        for now in steps:
            await self.simulate_timestep(now)
        if self.scale != TimeScale.day:
            for order_id in list(self.state.open_orders):
                await self.state.cancel(order_id)

    async def simulate_timestep(self, now: pd.Timestamp) -> None:
        """Simulate the step of at the time of a bar.

        Run only the active strategies, and only their filters and portfolio
        rules that are due.

        Parameters
        ----------
        now: pd.Timestamp
            The time of the bar.
        """
        await self._fill_open_orders(now)

        strategies = self.state.strategies.values()
        for strategy in strategies:
            filter = strategy.filter
            if strategy.active and filter is not None and filter.is_due(now):
                self.state.set_universe(
                    strategy.name, await filter.select(now)
                )

        decisions = []
        for symbol in sorted(self.state.symbols()):
            decisions += await self.state.decide_symbol(symbol, now)
        for strategy in strategies:
            rule = strategy.rule
            if isinstance(rule, PortfolioRule) and rule.is_due(now):
                decisions += await self.state.decide_portfolio(strategy, now)

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
                await self._fill_open_order(open_order, price, now)

    async def _fill_open_order(
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
                "strategy": open_order.strategy.name,
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
    number of trades and the open positions of each strategy to
    <batch_id>-summary.txt, both in the current directory.

    Parameters
    ----------
    batch_id: str
        The batch identifier of the session.
    trades: pd.DataFrame
        The trades, with the columns of TRADE_COLUMNS.
    positions: Dict[str, Dict]
        The open positions of each strategy, by strategy name and symbol.
    """
    trades.to_csv(f"{batch_id}-trades.csv", index=False)

    lines = [f"batch-id: {batch_id}"]
    for strategy, strategy_positions in positions.items():
        strategy_trades = trades[trades.strategy == strategy]
        lines += [
            f"strategy {strategy}:",
            f"  net cash flow: {net_cash_flow(strategy_trades):.2f}",
            f"  trades: {len(strategy_trades)}",
            f"  open positions: {strategy_positions}",
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
    tradeplan: list[dict],
    buy_fee_percentage: float,
    sell_fee_percentage: float,
    asset_type: AssetType,
) -> pd.DataFrame:
    """Prepare and run a complete backtesting session.

    Connect to the database, which the momentum filter reads, and create the
    components of the trade plan with a context of their own. Halt on an
    ownership collision if config.halt_on_collision is set. Write the
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
    tradeplan: list[dict]
        The strategy files of the trade plan.
    buy_fee_percentage: float
        The buy fee, as a percentage of the trade value.
    sell_fee_percentage: float
        The sell fee, as a percentage of the trade value.
    asset_type: AssetType
        The type of asset traded, which sets the market calendar.

    Returns
    -------
    Return the trades, with the columns of TRADE_COLUMNS.

    Raises
    ------
    Raise OwnershipCollision if a strategy requests a symbol that another
    strategy owns and config.halt_on_collision is set.
    """
    logger.info(
        "Starting back-test from %s to %s with time scale %s",
        from_date,
        to_date,
        scale,
    )

    await create_db_connection()

    ctx = Context(
        DataLoader(scale),
        trader_factory(),
        backtesting=True,
        asset_type=asset_type,
    )
    strategies = create_strategies(tradeplan, ctx)
    logger.info("strategies %s", list(strategies))

    session = Backtest(
        ctx,
        RunState(strategies, config.halt_on_collision),
        scale,
        buy_fee_percentage,
        sell_fee_percentage,
    )
    await session.simulate_range(from_date, to_date)

    trades = pd.DataFrame(session.trades, columns=TRADE_COLUMNS)
    write_results(uid, trades, session.state.positions)
    return trades


def backtest(
    from_date: date,
    to_date: date,
    scale: TimeScale,
    tradeplan: list[dict],
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
    tradeplan: list[dict]
        The strategy files of the trade plan.
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
                tradeplan,
                buy_fee_percentage,
                sell_fee_percentage,
                asset_type,
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
