import concurrent.futures
import logging
import time

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.data.data_loader import DataLoader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


def last_100_trading_days(now: pd.Timestamp) -> slice:
    start = pd.Timestamp(
        now.date() - pd.Timedelta(days=int(100 * 7 / 5)), tz=clock.NY
    )
    end = now.replace(hour=9, minute=30, second=0, microsecond=0, nanosecond=0)
    return slice(start, end)


@pytest.mark.devtest
def test_create_data_loader_default() -> bool:
    return bool(DataLoader(connector=DataConnectorType.alpaca))


@pytest.mark.devtest
def test_apple_stock_range() -> bool:
    logger.info("+ test_apple_stock_range()")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    start_time = time.time()
    data = dl["AAPL"][
        pd.Timestamp("2021-01-01", tz=clock.NY) : pd.Timestamp(
            "2021-10-01", tz=clock.NY
        )
    ]
    logger.info("1st load_time: %s", time.time() - start_time)

    start_time = time.time()
    data = dl["AAPL"][
        pd.Timestamp("2021-01-01", tz=clock.NY) : pd.Timestamp(
            "2021-10-01", tz=clock.NY
        )
    ]
    logger.info("2nd load_time: %s", time.time() - start_time)

    logger.info("- test_apple_stock_range()")

    return True


@pytest.mark.devtest
def test_apple_stock_range2() -> bool:
    logger.info("+ test_apple_stock_range2()")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    start_time = time.time()
    now = clock.now()
    data = dl["AAPL"][last_100_trading_days(now)]
    logger.info("1st load_time: %s", time.time() - start_time)

    start_time = time.time()
    data = dl["AAPL"][last_100_trading_days(now)]
    logger.info("2nd load_time: %s", time.time() - start_time)

    logger.info("- test_apple_stock_range2()")

    return True


@pytest.mark.devtest
def test_apple_stock_range3() -> bool:
    logger.info("+ test_apple_stock_range3()")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    start_time = time.time()
    now = clock.now()
    data = dl["AAPL"][last_100_trading_days(now)]
    logger.info("1st load_time: %s", time.time() - start_time)

    start_time = time.time()
    now = clock.now()
    data = dl["AAPL"][last_100_trading_days(now)]
    logger.info("2nd load_time: %s", time.time() - start_time)

    logger.info("- test_apple_stock_range3()")

    return True


def load_data_for_symbol(
    data_loader: DataLoader, symbol: str, now: pd.Timestamp
):
    start_time = time.time()

    data = data_loader[symbol][last_100_trading_days(now)]
    return time.time() - start_time


@pytest.mark.devtest
def test_apple_stock_range4() -> bool:
    logger.info("+ test_apple_stock_range4()")
    now = clock.now()
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Start the load operations and mark each future with its URL
        futures = {
            executor.submit(load_data_for_symbol, dl, symbol, now): symbol
            for symbol in ["AAPL"]
        }
        for future in concurrent.futures.as_completed(futures):
            logger.info("time-passed1 %s", future.result())
    now = clock.now()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Start the load operations and mark each future with its URL
        futures = {
            executor.submit(load_data_for_symbol, dl, symbol, now): symbol
            for symbol in ["AAPL"]
        }
        for future in concurrent.futures.as_completed(futures):
            logger.info("time-passed2 %s", future.result())

    logger.info("- test_apple_stock_range4()")

    return True
