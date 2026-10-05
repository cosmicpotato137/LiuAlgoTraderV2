import logging

import psutil

from liualgotrader.common import config
from liualgotrader.common.concurrency import calc_num_consumer_processes

logger = logging.getLogger(__name__)


def test_fix_num_consumer_processes(monkeypatch):
    logger.info("test_fix_num_consumer_processes")
    possible_values = [5, 8, 500]

    for num_consumers in possible_values:
        monkeypatch.setattr(config, "num_consumers", num_consumers)
        result = calc_num_consumer_processes()
        if result != num_consumers:
            raise AssertionError(
                f"calc_num_consumer_processes() - {result} returned, while expected {num_consumers}"
            )


def test_calc_num_consumer_processes(monkeypatch):
    logger.info("test_calc_num_consumer_processes")
    monkeypatch.setattr(config, "num_consumers", 0)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4)

    # Five processes per idle core, rounded down.
    for load_pct, expected in [(0.0, 20), (25.0, 15), (75.0, 5)]:
        monkeypatch.setattr(
            psutil, "cpu_percent", lambda interval=None: load_pct
        )
        result = calc_num_consumer_processes()
        if result != expected:
            raise AssertionError(
                f"calc_num_consumer_processes() - {result} returned at {load_pct}% load, while expected {expected}"
            )


def test_calc_num_consumer_processes_unknown_cpus(monkeypatch):
    logger.info("test_calc_num_consumer_processes_unknown_cpus")
    monkeypatch.setattr(config, "num_consumers", 0)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: None)

    result = calc_num_consumer_processes()
    if result != 1:
        raise AssertionError(
            f"calc_num_consumer_processes() - {result} returned, while expected 1"
        )
