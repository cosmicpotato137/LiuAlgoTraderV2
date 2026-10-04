import logging
import time

import psutil
import pytest

from liualgotrader.common import config
from liualgotrader.common.concurrency import calc_num_consumer_processes

logger = logging.getLogger(__name__)


def test_load_cpu_avg():
    logger.info("test_load_cpu_avg")
    cpu_load = psutil.cpu_percent(interval=5)
    num_cpus = psutil.cpu_count()

    logger.info("cpu_load = %s, num_cpus=%s", cpu_load, num_cpus)

    if cpu_load <= 0 or num_cpus <= 0:
        raise AssertionError("Unexpected result")


def test_fix_num_consumer_processes():
    logger.info("test_fix_num_consumer_processes")
    possible_values = [5, 8, 500]

    for num_consumers in possible_values:
        config.num_consumers = num_consumers
        result = calc_num_consumer_processes()
        if result != num_consumers:
            raise AssertionError(
                f"calc_num_consumer_processes() - {result} returned, while expected {num_consumers}"
            )


def test_calc_num_consumer_processes():
    logger.info("test_calc_num_consumer_processes")

    for _ in range(20):
        config.num_consumers = 0
        result = calc_num_consumer_processes()
        logger.info("calc_num_consumer_processes() -> %s", result)
        if result <= 0:
            raise AssertionError(
                f"calc_num_consumer_processes() - {result} unexpected"
            )

        time.sleep(10)
