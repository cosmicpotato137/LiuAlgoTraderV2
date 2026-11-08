import logging
import time

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.data.data_loader import DataLoader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


def days_ago(days: int) -> pd.Timestamp:
    return pd.Timestamp(clock.today() - pd.Timedelta(days=days), tz=clock.NY)


@pytest.mark.devtest
def test_multi_date_performance() -> bool:
    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.alpaca)

    t = time.time()
    dl["AAPL"][days_ago(20) : days_ago(10)]

    pref_single_apple = time.time() - t
    logger.info("load apple time spent %s", pref_single_apple)

    t = time.time()
    dl["IBM"][days_ago(20) : days_ago(10)]

    pref_single_ibm = time.time() - t
    logger.info("load ibm time spent %s", pref_single_ibm)

    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.alpaca)

    symbols = ["AAPL", "IBM", "TSLA", "WWBI"]
    end = clock.today()
    start = end - pd.Timedelta(days=200)

    t = time.time()
    dl.pre_fetch(symbols=symbols, start=start, end=end)
    pref = time.time() - t
    logger.info("load apple & ibm spent %s", pref)

    t = time.time()
    dl["AAPL"]
    pref = time.time() - t
    logger.info("multi 1 time spent %s", pref)

    t = time.time()
    dl["AAPL"][days_ago(20) : days_ago(10)]

    pref_multi = time.time() - t
    logger.info("multi 2 time spent %s", pref_multi)

    return True
