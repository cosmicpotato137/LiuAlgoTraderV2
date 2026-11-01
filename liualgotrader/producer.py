"""Get market data from data providers and pump it to the consumers.

Classes
-------
SymbolRouter
    Assign symbols to consumer queues and forward filter results.

Functions
---------
filter_input
    Route the filter results until cancelled.
producer_async_main
    Set up the producer and run its tasks.
producer_main
    Run the producer process.
"""

import asyncio
import json
import logging
import os
from multiprocessing import Queue
from queue import Empty
from typing import Dict, List

from liualgotrader.common import config
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import (QueueMessageType, SymbolQueueMap,
                                        WSEventType)
from liualgotrader.db.models.trending_tickers import TrendingTicker
from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.new_base import portfolio_filters
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.stream.factory import streaming_factory
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)


class SymbolRouter:
    """Assign symbols to consumer queues and forward filter results.

    A symbol from a portfolio filter goes to consumer 0, which runs the
    portfolio rules; any other new symbol goes to the consumer with the
    fewest symbols. The assignment of a symbol never changes.

    Attributes
    ----------
    queues: List[Queue]
        The consumer queues.
    portfolio_filters: set[str]
        The names of the filters that feed a portfolio rule.
    stream: StreamingAPI
        The market data stream.
    assigned: Dict[str, int]
        The consumer of each symbol, by symbol.

    Methods
    -------
    route
        Assign and subscribe new symbols, and forward filter results.
    """

    def __init__(
        self,
        queues: List[Queue],
        portfolio_filters: set[str],
        stream: StreamingAPI,
    ):
        """Initialize the router with no symbols assigned.

        Parameters
        ----------
        queues: List[Queue]
            The consumer queues.
        portfolio_filters: set[str]
            The names of the filters that feed a portfolio rule.
        stream: StreamingAPI
            The market data stream.
        """
        self.queues = queues
        self.portfolio_filters = portfolio_filters
        self.stream = stream
        self.assigned: Dict[str, int] = {}
        self._counts = [0] * len(queues)

    def _assign(self, symbol: str, filter_name: str) -> None:
        """Assign a new symbol to a consumer queue."""
        consumer = (
            0
            if filter_name in self.portfolio_filters
            else self._counts.index(min(self._counts))
        )
        self.assigned[symbol] = consumer
        self._counts[consumer] += 1
        self.stream.queues[symbol] = self.queues[consumer]

    async def route(self, filter_name: str, symbols: List[str]) -> None:
        """Assign and subscribe new symbols, and forward filter results to
        the proper queue.

        Send each consumer a filter_result message with the symbols assigned
        to it, even none, as the consumer replaces the filter's universe with
        them. Then subscribe the new symbols to second bars, minute bars and
        trades, and save them as trending tickers. Warn about a portfolio
        filter's symbol that another consumer already has, since portfolio
        rules never see it.

        Parameters
        ----------
        filter_name: str
            The name of the filter that selected the symbols.
        symbols: List[str]
            The symbols, in lower case.
        """
        new_symbols = []
        selections: List[List[str]] = [[] for _ in self.queues]
        for symbol in symbols:
            if symbol not in self.assigned:
                self._assign(symbol, filter_name)
                new_symbols.append(symbol)
            elif (
                filter_name in self.portfolio_filters and self.assigned[symbol]
            ):
                logger.warning(
                    "%s from portfolio filter %s is on consumer %s, so "
                    "portfolio rules will not see it",
                    symbol,
                    filter_name,
                    self.assigned[symbol],
                )
            selections[self.assigned[symbol]].append(symbol)
        for queue, selection in zip(self.queues, selections):
            queue.put(
                {
                    "EV": QueueMessageType.FILTER_RESULT,
                    "symbols": selection,
                    "filter_name": filter_name,
                }
            )

        if not new_symbols:
            return
        await self.stream.subscribe(
            new_symbols,
            [WSEventType.SEC_AGG, WSEventType.MIN_AGG, WSEventType.TRADE],
        )
        await TrendingTicker.save_symbols(
            config.batch_id, new_symbols, filter_name
        )
        logger.info(
            "added %s from %s, TOTAL: %s",
            new_symbols,
            filter_name,
            len(self.assigned),
        )


async def filter_input(filter_queue: Queue, router: SymbolRouter) -> None:
    """Route the results that the filters report until cancelled.

    Wait 30 seconds when no results are available. Log other exceptions and
    continue.

    Parameters
    ----------
    filter_queue: Queue
        The queue of filter results, each a JSON object with a filter_name
        and symbols.
    router: SymbolRouter
        The router of the results.
    """
    logger.info("filter_input() task starting")

    while True:
        try:
            result = json.loads(filter_queue.get(timeout=1))
            await router.route(result["filter_name"], result["symbols"])
        except Empty:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("filter_input() task cancelled")
            break
        except Exception:
            logger.exception("Exception in filter_input()")

    logger.info("filter_input() task completed")


async def producer_async_main(
    queues: List[Queue], filter_queue: Queue, tradeplan: Dict
):
    """Set up the producer and run its tasks until they finish.

    Create the database connection pool, start the market data stream and the
    trader, and collect task exceptions instead of raising them.

    Parameters
    ----------
    queues: List[Queue]
        The consumer queues.
    filter_queue: Queue
        The queue of filter results.
    tradeplan: Dict
        The trade plan.
    """
    await create_db_connection(str(config.dsn))
    router_filters = portfolio_filters(tradeplan)
    logger.info("portfolio filters: %s", router_filters)

    qm = SymbolQueueMap(queue_list=queues)
    stream = streaming_factory(qm)
    await stream.run()

    trade_updates_task = await trader_factory(qm).run()

    tasks = [
        asyncio.create_task(
            filter_input(
                filter_queue, SymbolRouter(queues, router_filters, stream)
            ),
            name="filter_input",
        )
    ]
    if trade_updates_task:
        tasks.append(trade_updates_task)

    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("producer_async_main() completed")


def producer_main(
    unique_id: str,
    queues: List[Queue],
    tradeplan: Dict,
    filter_queue: Queue,
) -> None:
    """Run the producer process until its tasks complete.

    Set the batch identifier in config. Log exceptions and keyboard interrupts
    instead of raising them.

    Parameters
    ----------
    unique_id: str
        The batch identifier of the run.
    queues: List[Queue]
        The consumer queues.
    tradeplan: Dict
        The trade plan.
    filter_queue: Queue
        The queue of filter results.
    """
    configure_logging()
    logger.info("*** producer_main() starting w pid %s ***", os.getpid())
    try:
        config.batch_id = unique_id
        asyncio.run(producer_async_main(queues, filter_queue, tradeplan))
    except KeyboardInterrupt:
        logger.info("producer_main() - Caught KeyboardInterrupt")
    except Exception:
        logger.exception("producer_main() failed")

    logger.info("*** producer_main() completed ***")
