"""Live trading with the trade plan.

Usage: trader
Trade live with the trade plan: the strategy files (*.toml) in TRADEPLAN_DIR,
or else in the current directory.

Functions
---------
motd
    Log the welcome banner.
main_cli
    Run the live trading processes from the command line and exit.
"""

import logging
import multiprocessing as mp
import os
import sys
import uuid
from multiprocessing import Queue, connection
from typing import List

from liualgotrader.common import config
from liualgotrader.common.concurrency import calc_num_consumer_processes
from liualgotrader.common.log import configure_logging
from liualgotrader.consumer import consumer_main
from liualgotrader.filters_runner import main as filters_main
from liualgotrader.producer import producer_main
from liualgotrader.strategy.tradeplan import load_tradeplan

logger = logging.getLogger(__name__)


def motd(filename: str, version: str, unique_id: str) -> None:
    """Log the welcome banner.

    Parameters
    ----------
    filename: str
        The script file name.
    version: str
        The build label.
    unique_id: str
        The batch identifier of the run.
    """
    logger.info("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    logger.info("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    logger.info("%s %s starting", filename, version)
    logger.info("unique id: %s", unique_id)
    logger.info("----------------------------------------------------------")
    logger.info("----------------------------------------------------------")


def main_cli():
    """Run the live trading processes from the command line and exit.

    Exit if the trade plan is not found.

    Raises
    ------
    Raise ValueError if a strategy file of the trade plan is not valid, see
    load_tradeplan.
    """
    configure_logging()
    config.filename = os.path.basename(__file__)
    mp.set_start_method("spawn")

    uid = str(uuid.uuid4())
    motd(filename=config.filename, version=config.build_label, unique_id=uid)

    try:
        tradeplan = load_tradeplan(config.tradeplan_folder)
    except FileNotFoundError as error:
        logger.error("could not locate the trade plan: %s", error)
        sys.exit(0)
    logger.debug("trade plan: %s", tradeplan)

    # Consumers first
    num_consumer_processes = calc_num_consumer_processes()
    logger.info("Starting %s consumer processes", num_consumer_processes)
    queues: List[Queue] = [Queue() for _ in range(num_consumer_processes)]
    consumers = [
        mp.Process(
            target=consumer_main,
            args=(queues[i], tradeplan, i == 0),
        )
        for i in range(num_consumer_processes)
    ]
    for p in consumers:
        # p.daemon = True
        p.start()

    filter_queue: mp.Queue = mp.Queue()
    producer = mp.Process(
        target=producer_main,
        args=(uid, queues, tradeplan, filter_queue),
    )
    producer.start()

    logger.info("Starting filters process")
    filters = mp.Process(target=filters_main, args=(tradeplan, filter_queue))
    filters.start()

    # consumers run until interrupted or halted, so the first to exit ends
    # the run
    try:
        connection.wait([p.sentinel for p in consumers])
    except KeyboardInterrupt:
        logger.info("Caught KeyboardInterrupt, stopping")
    failed = [p for p in consumers if p.exitcode]
    for p in failed:
        logger.error(
            "consumer %s exited with status %s, stopping", p.pid, p.exitcode
        )

    producer.kill()
    filters.terminate()

    for p in consumers:
        p.terminate()

    sys.exit(1 if failed else 0)
