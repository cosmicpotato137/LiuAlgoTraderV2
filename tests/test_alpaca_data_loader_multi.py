import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import pytest
from pytz import timezone

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import DataConnectorType, TimeScale

logger = logging.getLogger(__name__)

nyc = timezone("America/New_York")


@pytest.mark.devtest
def test_multi_date_performance() -> bool:
    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.alpaca)

    t = time.time()
    dl["AAPL"][
        (datetime.now().date() - timedelta(days=20)) : (
            datetime.now().date() - timedelta(days=10)
        )
    ]

    pref_single_apple = time.time() - t
    logger.info("load apple time spent %s", pref_single_apple)

    t = time.time()
    dl["IBM"][
        (datetime.now().date() - timedelta(days=20)) : (
            datetime.now().date() - timedelta(days=10)
        )
    ]

    pref_single_ibm = time.time() - t
    logger.info("load ibm time spent %s", pref_single_ibm)

    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.alpaca)

    symbols = ["AAPL", "IBM", "TSLA", "WWBI"]
    end = datetime.now().date()
    start = end - timedelta(days=200)

    t = time.time()
    dl.pre_fetch(symbols=symbols, start=start, end=end)
    pref = time.time() - t
    logger.info("load apple & ibm spent %s", pref)

    t = time.time()
    dl["AAPL"]
    pref = time.time() - t
    logger.info("multi 1 time spent %s", pref)

    t = time.time()
    dl["AAPL"][
        (datetime.now().date() - timedelta(days=20)) : (
            datetime.now().date() - timedelta(days=10)
        )
    ]

    pref_multi = time.time() - t
    logger.info("multi 2 time spent %s", pref_multi)

    return True
