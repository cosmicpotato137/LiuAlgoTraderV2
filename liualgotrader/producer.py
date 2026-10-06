"""Get market data from data providers and pump it to the consumers.

Functions
---------
get_new_symbols_and_queues
    Return untracked symbols and assign queues.
subscribe_new_symbols
    Subscribe to market data for new symbols.
scanners_iteration
    Process one batch of scanner results.
scanner_input
    Subscribe to scanner results until cancelled.
trade_run
    Run the configured trader.
dispense_strategies
    Send trade plan entries to the consumers.
tradeplan_scanner
    Dispatch new trade plan entries every five minutes.
run
    Start the market data stream.
producer_async_main
    Set up the producer and run its tasks.
producer_main
    Run the producer process.
"""

import asyncio
import inspect
import json
import logging
import os
import random
from multiprocessing import Queue
from queue import Empty
from typing import Dict, List

import pandas as pd

from liualgotrader.common import clock, config
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import SymbolQueueMap, WSEventType
from liualgotrader.db.models.tradeplan import TradePlan
from liualgotrader.db.models.trending_tickers import TrendingTicker
from liualgotrader.db.session import create_db_connection
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.stream.factory import streaming_factory
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)

last_msg_tstamp: pd.Timestamp = clock.now()
symbols: List[str] = []
queue_id_hash: Dict[str, int] = {}
symbol_strategy: Dict = {}


def get_new_symbols_and_queues(
    symbols_details: Dict, queues: List[Queue], num_consumer_processes: int
) -> List[str]:
    """Return the symbols not yet tracked and assign each one a queue.

    Record the target strategy of each new symbol and map it to a randomly
    chosen queue in the streaming instance. Leave the tracked list unchanged.

    Parameters
    ----------
    symbols_details: Dict
        The scanner results, each with a symbol and a target strategy name.
    queues: List[Queue]
        The consumer queues.
    num_consumer_processes: int
        The number of queues to choose from.
    """
    global symbol_strategy
    global symbols

    new_symbols: List = []
    for symbol_details in symbols_details:
        symbol = symbol_details["symbol"].lower()
        if symbol not in symbols:
            new_symbols.append(symbol)
            symbol_strategy[symbol] = symbol_details["target_strategy_name"]
            StreamingAPI.get_instance().queues[symbol] = queues[
                random.SystemRandom().randint(0, num_consumer_processes - 1)
            ]

    return new_symbols


async def subscribe_new_symbols(new_symbols: List[str]):
    """Subscribe the stream to aggregates and trades for new_symbols.

    Parameters
    ----------
    new_symbols: List[str]
        The symbols to subscribe to.
    """
    await StreamingAPI.get_instance().subscribe(
        new_symbols,
        [
            WSEventType.SEC_AGG,
            WSEventType.MIN_AGG,
            WSEventType.TRADE,
        ],
    )


async def scanners_iteration(
    scanner_queue: Queue,
    queues: List[Queue],
    num_consumer_processes: int,
):
    """Subscribe to the new symbols in one batch of scanner results.

    Save the new symbols to the trending tickers table and add them to the
    tracked list.

    Parameters
    ----------
    scanner_queue: Queue
        The queue of scanner results.
    queues: List[Queue]
        The consumer queues.
    num_consumer_processes: int
        The number of consumer queues in use.

    Raises
    ------
    Raise Empty if no results arrive within a second.
    """
    global symbols
    symbols_details = scanner_queue.get(timeout=1)
    if len(
        new_symbols := get_new_symbols_and_queues(
            symbols_details=json.loads(symbols_details),
            queues=queues,
            num_consumer_processes=num_consumer_processes,
        )
    ):
        await subscribe_new_symbols(new_symbols)
        await TrendingTicker.save_symbols(config.batch_id, new_symbols)
        symbols += new_symbols
        logger.info(
            "added %s:%s..%s TOTAL: %s",
            len(new_symbols),
            new_symbols[:20],
            new_symbols[-20:],
            len(symbols),
        )
        await asyncio.sleep(1)


async def scanner_input(
    scanner_queue: Queue,
    queues: List[Queue],
    num_consumer_processes: int,
) -> None:
    """Subscribe to the symbols reported by the scanners until cancelled.

    Wait 30 seconds when no results are available. Log other exceptions and
    continue.

    Parameters
    ----------
    scanner_queue: Queue
        The queue of scanner results.
    queues: List[Queue]
        The consumer queues.
    num_consumer_processes: int
        The number of consumer queues in use.
    """
    logger.info("scanner_input() task starting ")

    while True:
        try:
            await scanners_iteration(
                scanner_queue=scanner_queue,
                queues=queues,
                num_consumer_processes=num_consumer_processes,
            )
        except Empty:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("scanner_input() task task cancelled ")
            break
        except Exception as e:
            logger.error(
                "Exception in scanner_input(): exception of type %s with args %s",
                type(e).__name__,
                e.args,
                exc_info=config.debug_enabled,
            )

    logger.info("scanner_input() task completed")


async def trade_run(qm: SymbolQueueMap) -> None:
    """Run the configured trader.

    Parameters
    ----------
    qm: QueueMapper
        The queue mapper passed to the trader.
    """
    at = trader_factory(qm)
    logger.info("trade_run() starting using %s trading", at)
    await at.run()
    logger.info("trade_run() completed")


async def dispense_strategies(
    consumer_queues: List[Queue], tradeplan_entries: List[TradePlan]
) -> None:
    """Send each trade plan entry to a randomly chosen consumer queue.

    Log a failure to send an entry and continue with the rest.

    Parameters
    ----------
    consumer_queues: List[Queue]
        The consumer queues.
    tradeplan_entries: List[TradePlan]
        The trade plan entries to send.
    """
    for tradeplan in tradeplan_entries:
        happy_consumer = consumer_queues[
            random.SystemRandom().randint(0, len(consumer_queues) - 1)
        ]

        payload = {
            "EV": "new_strategy",
            "parameters": tradeplan.parameters,
            "portfolio_id": tradeplan.portfolio_id,
        }

        try:
            happy_consumer.put(payload)
        except Exception as e:
            logger.error(
                "Exception in dispense_strategies: exception of type %s with args %s",
                type(e).__name__,
                e.args,
                exc_info=config.debug_enabled,
            )


async def tradeplan_scanner(
    consumer_queues: List[Queue],
) -> None:
    """Dispatch new trade plan entries to the consumers every five minutes.

    Send the active entries created since the previous scan. Log exceptions and
    continue.

    Parameters
    ----------
    consumer_queues: List[Queue]
        The consumer queues.
    """
    logger.info("tradeplan_scanner() task starting ")

    last_scan = clock.now()
    while True:
        await asyncio.sleep(5 * 60)

        logger.info(
            "tradeplan_scanner(): check for new execution requests since %s",
            last_scan,
        )
        try:
            new_tradeplan_entries = await TradePlan.get_new_entries(
                since=last_scan
            )
            last_scan = clock.now()

            if new_tradeplan_entries:
                logger.info(
                    "found %s new tradeplan entries for execution",
                    len(new_tradeplan_entries),
                )
                await dispense_strategies(
                    consumer_queues, new_tradeplan_entries
                )
        except Exception as e:
            logger.error(
                "tradeplan_scanner() %s", e, exc_info=config.debug_enabled
            )

    logger.info("tradeplan_scanner() task completed")


async def run(
    queues: List[Queue],
    qm: SymbolQueueMap,
) -> None:
    """Start the market data stream and subscribe to the tracked symbols.

    Map each tracked symbol in qm to its assigned consumer queue.

    Parameters
    ----------
    queues: List[Queue]
        The consumer queues.
    qm: QueueMapper
        The queue mapper of the stream.
    """
    global queue_id_hash

    ps = streaming_factory(qm)
    await ps.run()
    for symbol in symbols:
        symbol = symbol.lower()
        qm[symbol] = queues[queue_id_hash[symbol]]
    await ps.subscribe(
        symbols, [WSEventType.SEC_AGG, WSEventType.MIN_AGG, WSEventType.TRADE]
    )


"""
process main
"""


async def producer_async_main(
    queues: List[Queue],
    scanner_queue: Queue,
    num_consumer_processes: int,
):
    """Set up the producer and run its tasks until they finish.

    Create the database connection pool, start the market data stream and the
    trader, and collect task exceptions instead of raising them.

    Parameters
    ----------
    queues: List[Queue]
        The consumer queues.
    scanner_queue: Queue
        The queue of scanner results.
    num_consumer_processes: int
        The number of consumer queues in use.
    """
    await create_db_connection(str(config.dsn))
    qm = SymbolQueueMap(queue_list=queues)
    await run(queues=queues, qm=qm)

    at = trader_factory(qm)
    trade_updates_task = await at.run()

    scanner_input_task = asyncio.create_task(
        scanner_input(scanner_queue, queues, num_consumer_processes),
        name="scanner_input",
    )

    tradeplan_scanner_task = asyncio.create_task(
        tradeplan_scanner(queues), name="tradeplan_scanner"
    )

    async_tasks_to_gather = [scanner_input_task, tradeplan_scanner_task]

    if inspect.iscoroutinefunction(trade_updates_task):
        async_tasks_to_gather.append(trade_updates_task)  # type: ignore

    await asyncio.gather(
        *async_tasks_to_gather,
        return_exceptions=True,
    )

    logger.info("producer_async_main() completed")


def producer_main(
    unique_id: str,
    queues: List[Queue],
    conf_dict: Dict,
    scanner_queue: Queue,
    num_consumer_processes: int,
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
    conf_dict: Dict
        Unused.
    scanner_queue: Queue
        The queue of scanner results.
    num_consumer_processes: int
        The number of consumer queues in use.
    """
    configure_logging()
    logger.info("*** producer_main() starting w pid %s ***", os.getpid())
    try:
        config.batch_id = unique_id
        asyncio.run(
            producer_async_main(queues, scanner_queue, num_consumer_processes)
        )
    except KeyboardInterrupt:
        logger.info("producer_main() - Caught KeyboardInterrupt")
    except Exception as e:
        logger.error(
            "producer_main() - exception of type %s with args %s",
            type(e).__name__,
            e.args,
            exc_info=config.debug_enabled,
        )

    logger.info("*** producer_main() completed ***")
