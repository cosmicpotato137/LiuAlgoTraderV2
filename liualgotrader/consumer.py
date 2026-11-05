"""Run the rules of the trade plan on the data that the producer streams.

Classes
-------
Consumer
    The run state and tasks of a consumer process.

Functions
---------
aggregate_bar_data
    Merge a streamed bar into the minute data.
consumer_async_main
    Set up the consumer and run its tasks.
consumer_main
    Run a consumer process.
"""

import asyncio
import logging
import math
import os
import sys
from multiprocessing import Queue
from queue import Empty
from random import randint
from typing import Dict, Optional, cast

import pandas as pd

from liualgotrader.common import clock, config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.exceptions import OwnershipCollision
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import Order, QueueMessageType, Trade
from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.new_base import (Context, OrderRequest,
                                             PortfolioRule, Strategy)
from liualgotrader.strategy.runtime import OpenOrder, RunState
from liualgotrader.strategy.tradeplan import create_strategies
from liualgotrader.trade.base import TraderAPI
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)

# How long an order may stay open before the consumer cancels it.
_STALE_ORDER_AGE = pd.Timedelta(minutes=1)


async def aggregate_bar_data(
    data_loader: DataLoader, data: Dict, ts: pd.Timestamp
) -> None:
    """Merge a streamed bar into the minute data held by data_loader.

    Let a minute bar replace the bar for its minute, and combine other
    messages with the existing bar.

    Parameters
    ----------
    data_loader: DataLoader
        The loader that holds the minute data.
    data: Dict
        The bar message.
    ts: pd.Timestamp
        The bar timestamp; its seconds are ignored.
    """
    ts = ts.replace(second=0)
    symbol = data["symbol"].lower()

    if not data_loader.exist(symbol):
        data_loader[symbol][-1]

    try:
        current = data_loader[symbol].loc[ts]
    except KeyError:
        current = None

    if current is None or data["EV"] == QueueMessageType.MINUTE_BAR:
        new_data = [
            data["open"],
            data["high"],
            data["low"],
            data["close"],
            data["volume"],
            data["vwap"],
            data["average"],
            int(data["count"]),
        ]
    else:
        new_data = [
            current["open"],
            max(data["high"], current["high"]),
            min(data["low"], current["low"]),
            data["close"],
            current["volume"] + data["volume"],
            data["vwap"] or current["vwap"],
            (
                current["average"]
                if math.isnan(data["average"])
                else data["average"]
            ),
            int(data["count"] + current["count"]),
        ]

    try:
        data_loader[symbol].loc[ts] = new_data
    except ValueError:
        logger.debug("loaded for %s %s", symbol, new_data)
        data_loader[symbol][-1]
        data_loader[symbol].loc[ts] = new_data


class Consumer:
    """The run state and tasks of a consumer process.

    Attributes
    ----------
    ctx: Context
        The context of the run.
    trader: TraderAPI
        The trader of the context, which submits and cancels orders.
    state: RunState
        The universes, positions, open orders and owners of the run.
    run_portfolio_rules: bool
        Whether this consumer runs the portfolio rules.

    Methods
    -------
    check_order
        Reconcile a stale order with the broker and cancel it unless filled.
    handle_market_data
        Add a bar to the data and run the symbol rules on a minute bar.
    queue_consumer
        Consume and dispatch the messages of the producer.
    portfolio_runner
        Run a portfolio rule at its recurrence.
    cancel_lingering_orders
        Check the stale orders once a minute.
    run
        Run the tasks of the consumer.
    """

    def __init__(
        self, ctx: Context, state: RunState, run_portfolio_rules: bool
    ):
        """Initialize the consumer.

        Parameters
        ----------
        ctx: Context
            The context of the run, with a trader.
        state: RunState
            The run state, which holds the strategies of the trade plan.
        run_portfolio_rules: bool
            Whether this consumer runs the portfolio rules.

        Raises
        ------
        Raise ValueError if the context has no trader.
        """
        if ctx.trader is None:
            raise ValueError("the consumer needs a trader")
        self.ctx = ctx
        self.trader: TraderAPI = ctx.trader
        self.state = state
        self.run_portfolio_rules = run_portfolio_rules
        self._time_tick: Dict[str, pd.Timestamp] = {}

    async def _place(self, request: OrderRequest) -> Optional[Order]:
        """Submit an order to the broker as a day order."""
        order = await self.trader.submit_order(
            symbol=request.symbol,
            qty=request.qty,
            side=request.side.name,
            order_type=request.type,
            time_in_force="day",
            limit_price=(
                None  # type: ignore[arg-type]
                if request.limit_price is None
                else str(request.limit_price)
            ),
        )
        logger.info("submitted %s", order)
        return order

    async def check_order(
        self, open_order: OpenOrder, now: pd.Timestamp
    ) -> None:
        """Reconcile a stale order with the broker and cancel it unless filled.

        Apply the fills that the broker reports and that no trade update has
        applied yet. Cancel an order that is not completely filled, and drop
        it once the broker accepts. Log exceptions instead of raising them.

        Parameters
        ----------
        open_order: OpenOrder
            The open order.
        now: pd.Timestamp
            The current time.
        """
        order, request = open_order.order, open_order.request
        try:
            status, price, filled_qty, fee = (
                await self.trader.is_order_completed(
                    order.order_id, order.external_account_id
                )
            )
            unapplied = max((filled_qty or 0.0) - open_order.filled_qty, 0.0)
            if status == Order.EventType.fill or unapplied > 0:
                await self.state.fill_order(
                    open_order,
                    unapplied,
                    price or 0.0,
                    fee or 0.0,
                    now,
                    final=status == Order.EventType.fill,
                )
            if status == Order.EventType.fill:
                return

            logger.info(
                "canceling order %s for %s submitted at %s",
                order.order_id,
                request.symbol,
                order.submitted_at,
            )
            if await self.trader.cancel_order(order):
                await self.state.cancel(order.order_id)
        except Exception:
            logger.exception("check_order() failed for %s", order)

    async def handle_market_data(self, data: Dict) -> None:
        """Add a bar to the data and run the symbol rules on a minute bar.

        Skip a message other than a minute bar that is more than 15 seconds
        late or repeats the previous second of its symbol. Check the stale
        open orders of the symbol. On a minute bar, advance the horizon of the
        context to the time of the bar, run the symbol rules with now set to
        it and submit the orders they request.

        Parameters
        ----------
        data: Dict
            The market data message.
        """
        symbol = data["symbol"].lower()
        is_minute_bar = data["EV"] == QueueMessageType.MINUTE_BAR
        second = data["timestamp"].replace(microsecond=0, nanosecond=0)

        if not is_minute_bar:
            time_diff = clock.now() - data["timestamp"]
            if time_diff > pd.Timedelta(seconds=15):
                if randint(1, 100) == 1:  # nosec
                    logger.info(
                        "%s %s too out of sync w %s",
                        data["EV"],
                        symbol,
                        time_diff,
                    )
                return
            if self._time_tick.get(symbol) == second:
                return
            self._time_tick[symbol] = second

        await aggregate_bar_data(self.ctx.data_loader, data, second)
        self.ctx.invalidate(symbol)

        for open_order in self.state.stale_orders(
            second - _STALE_ORDER_AGE, symbol
        ):
            await self.check_order(open_order, second)

        if is_minute_bar:
            minute = second.replace(second=0)
            self.ctx.set_horizon(minute)
            decisions = await self.state.decide_symbol(symbol, minute)
            await self.state.submit(decisions, self._place)

    async def queue_consumer(self, queue: Queue) -> None:
        """Consume and dispatch the messages of the producer until cancelled.

        Apply trade updates, replace the universe of a strategy with each
        result of its filter and handle market data; log an error for a message of unknown
        type. On a ConnectionError, reconnect the trader and put the message
        back on queue. Log other exceptions and continue, except
        OwnershipCollision.

        Parameters
        ----------
        queue: Queue
            The queue to read from.

        Raises
        ------
        Raise OwnershipCollision if a strategy requests a symbol that another
        strategy owns and the run state halts on collisions.
        """
        logger.info("queue_consumer() starting")
        try:
            while True:
                try:
                    data = queue.get(timeout=2)
                    match data["EV"]:
                        case QueueMessageType.TRADE_UPDATE:
                            logger.info("received trade_update: %s", data)
                            await self.state.handle_trade(
                                Trade(**data["trade"])
                            )
                        case QueueMessageType.FILTER_RESULT:
                            self.state.set_universe(
                                data["filter_name"], data["symbols"]
                            )
                        case (
                            QueueMessageType.MINUTE_BAR
                            | QueueMessageType.SECOND_BAR
                            | QueueMessageType.TRADE
                            | QueueMessageType.QUOTE
                        ):
                            await self.handle_market_data(data)
                        case _:
                            logger.error(
                                "queue_consumer(): unknown message type %s: "
                                "%s",
                                data["EV"],
                                data,
                            )

                except Empty:
                    await asyncio.sleep(0)
                except ConnectionError:
                    await self.trader.reconnect()
                    # re-post back to queue
                    queue.put(data, timeout=1)
                    await asyncio.sleep(1)
                except OwnershipCollision:
                    raise
                except Exception:
                    logger.exception("Exception in queue_consumer() loop")

        except asyncio.CancelledError:
            logger.info("queue_consumer() cancelled")
        finally:
            logger.info("queue_consumer() task done.")

    async def portfolio_runner(self, strategy: Strategy) -> None:
        """Run a portfolio strategy at the recurrence of its rule until
        cancelled or inactive.

        Skip runs while the market is closed. Pass the rule the time of the
        latest completed minute bar, and submit the orders it requests. Log
        the exceptions of a run and continue, except OwnershipCollision.

        Parameters
        ----------
        strategy: Strategy
            The strategy, whose rule is a PortfolioRule.

        Raises
        ------
        Raise OwnershipCollision if the rule requests a symbol that another
        strategy owns and the run state halts on collisions.
        """
        rule = cast(PortfolioRule, strategy.rule)
        logger.info("portfolio_runner(%s) task starting", strategy)
        while strategy.active:
            await asyncio.sleep(rule.recurrence.total_seconds())
            try:
                now = clock.now()
                if not self.trader.is_market_open(now):
                    continue
                latest_bar = now.floor("min") - pd.Timedelta(minutes=1)
                decisions = await self.state.decide_portfolio(
                    strategy, latest_bar
                )
                await self.state.submit(decisions, self._place)
            except OwnershipCollision:
                raise
            except Exception:
                logger.exception("portfolio_runner(%s) failed", strategy)
        logger.info(
            "portfolio_runner(%s) task done, strategy inactive", strategy
        )

    async def cancel_lingering_orders(self) -> None:
        """Check the stale open orders once a minute until cancelled.

        Act only while the market is open.
        """
        logger.info("cancel_lingering_orders() task starting")

        while True:
            await asyncio.sleep(60)

            if not self.state.open_orders:
                continue

            now = clock.now()
            if not self.trader.is_market_open(now):
                logger.info("cancel_lingering_orders() market is closed")
                continue

            for open_order in self.state.stale_orders(now - _STALE_ORDER_AGE):
                await self.check_order(open_order, now)

    async def run(self, queue: Queue) -> None:
        """Run the tasks of the consumer until they finish.

        Run the queue consumer and the lingering-order check, and a runner
        for each portfolio rule if this consumer runs them. Collect task
        exceptions instead of raising them, except OwnershipCollision, which
        cancels the other tasks.

        Parameters
        ----------
        queue: Queue
            The queue of messages from the producer.

        Raises
        ------
        Raise OwnershipCollision if a strategy requests a symbol that another
        strategy owns and the run state halts on collisions.
        """
        coros = [self.queue_consumer(queue), self.cancel_lingering_orders()]
        if self.run_portfolio_rules:
            coros += [
                self.portfolio_runner(strategy)
                for strategy in self.state.strategies.values()
                if isinstance(strategy.rule, PortfolioRule)
            ]
        pending = {asyncio.ensure_future(coro) for coro in coros}
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                error = None if task.cancelled() else task.exception()
                if isinstance(error, OwnershipCollision):
                    for other in pending:
                        other.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    raise error


async def consumer_async_main(
    queue: Queue, tradeplan: list[dict], run_portfolio_rules: bool
) -> None:
    """Set up the consumer and run its tasks until they finish.

    Create the database connection pool, and a context and strategies of its
    own. Filters run in a separate process.

    Parameters
    ----------
    queue: Queue
        The queue of messages from the producer.
    tradeplan: list[dict]
        The strategy files of the trade plan.
    run_portfolio_rules: bool
        Whether this consumer runs the portfolio rules.

    Raises
    ------
    Raise OwnershipCollision if a strategy requests a symbol that another
    strategy owns and config.halt_on_collision is set.
    """
    await create_db_connection(str(config.dsn))
    ctx = Context(DataLoader(), trader=trader_factory())
    strategies = create_strategies(tradeplan, ctx, with_filters=False)
    logger.info("loaded strategies %s", list(strategies))

    state = RunState(strategies, config.halt_on_collision)
    await Consumer(ctx, state, run_portfolio_rules).run(queue)

    logger.info("consumer_async_main() completed")


def consumer_main(
    queue: Queue, tradeplan: list[dict], run_portfolio_rules: bool = False
) -> None:
    """Run a consumer process until its tasks complete.

    Log a keyboard interrupt instead of raising it. Exit with status 1 on an
    ownership collision, so that the trader stops its other processes.

    Parameters
    ----------
    queue: Queue
        The queue of messages from the producer.
    tradeplan: list[dict]
        The strategy files of the trade plan.
    run_portfolio_rules: bool, default False
        Whether this consumer runs the portfolio rules.
    """
    configure_logging()
    logger.info("*** consumer_main() starting w pid %s ***", os.getpid())

    halted = False
    try:
        asyncio.run(consumer_async_main(queue, tradeplan, run_portfolio_rules))
    except KeyboardInterrupt:
        logger.info("consumer_main() - Caught KeyboardInterrupt")
    except OwnershipCollision as collision:
        logger.critical("consumer_main() - halting: %s", collision)
        halted = True

    logger.info("*** consumer_main() completed ***")
    if halted:
        sys.exit(1)
