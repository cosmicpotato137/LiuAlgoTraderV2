"""Run the filters of the trade plan and pump their symbols to the producer.

Functions
---------
filter_runner
    Run a filter and publish the symbols it selects.
async_main
    Connect to the database and run the filters.
main
    Run the filter process.
"""

import asyncio
import json
import logging
import multiprocessing as mp
import os

from liualgotrader.common import clock, config
from liualgotrader.common.log import configure_logging
from liualgotrader.data.data_loader import DataLoader
from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.base import Context, Filter
from liualgotrader.strategy.tradeplan import create_filters
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)


async def filter_runner(selector: Filter, queue: mp.Queue) -> None:
    """Run a filter and publish the symbols it selects to queue.

    Put the JSON object {filter_name, symbols} on queue after each run, even
    one that selects no symbols, since each run replaces the universe of the
    filter's strategy, whose name the filter has. Repeat at the recurrence of
    the filter, or run once if it has none. Log exceptions instead of raising
    them.

    Parameters
    ----------
    selector: Filter
        The filter to run.
    queue: mp.Queue
        The queue that receives the results.
    """
    try:
        while True:
            symbols = await selector.select(clock.now())

            logger.info(
                "filter %s picked %s symbols", selector.name, len(symbols)
            )
            queue.put(
                json.dumps({"filter_name": selector.name, "symbols": symbols})
            )

            if not selector.recurrence:
                break

            await asyncio.sleep(selector.recurrence.total_seconds())
            logger.info("filter %s re-running", selector.name)
    except asyncio.CancelledError:
        logger.info("filter_runner() cancelled, closing %s", selector.name)
    except Exception:
        logger.exception("filter_runner(%s) failed", selector.name)
    finally:
        logger.info("filter_runner %s completed", selector.name)


async def async_main(tradeplan: list[dict], queue: mp.Queue) -> None:
    """Connect to the database and run the filters of a trade plan.

    Create the filters with a context of their own, whose trader answers
    read-only queries such as the tradeable symbols. Run them concurrently
    and close queue when they finish.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files of the trade plan.
    queue: mp.Queue
        The queue that receives the filter results.
    """
    await create_db_connection(str(config.dsn))

    ctx = Context(DataLoader(), trader=trader_factory())
    filters = create_filters(tradeplan, ctx)
    logger.info("running filters %s", list(filters))
    try:
        await asyncio.gather(
            *(filter_runner(f, queue) for f in filters.values())
        )
    finally:
        queue.close()


def main(tradeplan: list[dict], queue: mp.Queue) -> None:
    """Run the filter process until all filters complete.

    Log exceptions and keyboard interrupts instead of raising them.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files of the trade plan.
    queue: mp.Queue
        The queue that receives the filter results.
    """
    configure_logging()
    logger.info("*** filters_runner.main() starting w pid %s ***", os.getpid())

    try:
        asyncio.run(async_main(tradeplan, queue))
    except KeyboardInterrupt:
        logger.info("filters_runner.main() - Caught KeyboardInterrupt")
    except Exception:
        logger.exception("filters_runner.main() failed")

    logger.info("*** filters_runner.main() completed ***")
