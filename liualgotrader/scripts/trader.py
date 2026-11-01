"""Live trading with the trade plan.

Usage: trader
Trade live with the trade plan, tradeplan.toml, read from TRADEPLAN_DIR or
else the current directory.

Functions
---------
motd
    Log the welcome banner.
main_cli
    Run the live trading processes from the command line and exit.
"""

import copy
import logging
import multiprocessing as mp
import os
import sys
import uuid
from multiprocessing import Queue
from typing import List

import toml

from liualgotrader.common import config
from liualgotrader.common.concurrency import calc_num_consumer_processes
from liualgotrader.common.log import configure_logging
from liualgotrader.consumer import consumer_main
from liualgotrader.filters_runner import main as filters_main
from liualgotrader.producer import producer_main

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

    Start the consumer, producer and filter processes and wait for them to
    finish. Only the first consumer runs the portfolio rules. Stop them all on
    a keyboard interrupt. Exit if the trade plan is not found or has no
    filters section.
    """
    configure_logging()
    config.filename = os.path.basename(__file__)
    mp.set_start_method("spawn")

    uid = str(uuid.uuid4())
    motd(filename=config.filename, version=config.build_label, unique_id=uid)

    # load configuration
    folder = (
        config.tradeplan_folder
        if config.tradeplan_folder[-1] == "/"
        else f"{config.tradeplan_folder}/"
    )
    fname = f"{folder}{config.configuration_filename}"
    try:
        conf_dict = copy.deepcopy(toml.load(fname))
        logger.debug("configuration: %s", conf_dict)
        logger.info("loaded configuration file from %s", fname)
    except FileNotFoundError:
        logger.error("could not locate tradeplan file %s", fname)
        sys.exit(0)

    if not conf_dict.get("filters"):
        logger.error("tradeplan file %s has no [filters] section", fname)
        sys.exit(1)

    # Consumers first
    num_consumer_processes = calc_num_consumer_processes()
    logger.info("Starting %s consumer processes", num_consumer_processes)
    queues: List[Queue] = [Queue() for _ in range(num_consumer_processes)]
    consumers = [
        mp.Process(
            target=consumer_main,
            args=(queues[i], conf_dict, i == 0),
        )
        for i in range(num_consumer_processes)
    ]
    for p in consumers:
        # p.daemon = True
        p.start()

    filter_queue: mp.Queue = mp.Queue()
    producer = mp.Process(
        target=producer_main,
        args=(uid, queues, conf_dict, filter_queue),
    )
    producer.start()

    logger.info("Starting filters process")
    filters = mp.Process(target=filters_main, args=(conf_dict, filter_queue))
    filters.start()

    # wait for completion and hope everyone plays nicely
    try:
        producer.join()
        filters.join()

        for p in consumers:
            p.join()

    except KeyboardInterrupt:
        producer.kill()
        filters.terminate()

        for p in consumers:
            p.terminate()

    sys.exit(0)
