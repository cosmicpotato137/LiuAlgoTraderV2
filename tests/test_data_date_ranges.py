import logging
import time
from datetime import date

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from liualgotrader.common import clock
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.data.factory import data_api_factory

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


def test_alpaca_num_trading_day():
    logger.info("test_alpaca_num_trading_days_positive")
    alpaca_dl = data_api_factory(DataConnectorType.alpaca)
    if (
        alpaca_dl.num_trading_days(
            symbol="AAPL", start=date(2022, 1, 6), end=date(2022, 1, 7)
        )
        != 2
    ):
        raise AssertionError("expected 2")

    if (
        alpaca_dl.num_trading_days(
            symbol="aapl", start=date(2022, 1, 6), end=date(2022, 1, 7)
        )
        != 2
    ):
        raise AssertionError("expected 2")

    if (
        alpaca_dl.num_trading_days(
            symbol="AAPL", start=date(2022, 1, 1), end=date(2022, 1, 7)
        )
        != 5
    ):
        raise AssertionError("expected 5")

    if (
        alpaca_dl.num_trading_days(
            symbol="AAPL", start=date(2021, 12, 28), end=date(2022, 1, 7)
        )
        != 9
    ):
        raise AssertionError("expected 9")

    if (
        alpaca_dl.num_trading_days(
            symbol="AAPL", start=date(2021, 7, 1), end=date(2021, 7, 7)
        )
        != 4
    ):
        raise AssertionError("expected 4")

    if (
        alpaca_dl.num_trading_days(
            symbol="BTCUSD", start=date(2021, 7, 1), end=date(2021, 7, 7)
        )
        != 7
    ):
        raise AssertionError("BTCUSD - expected 7")

    if (
        alpaca_dl.num_trading_days(
            symbol="AAPL", start=date(2022, 8, 6), end=date(2022, 1, 7)
        )
        != 0
    ):
        raise AssertionError("expected 0")

    return True


def test_alpaca_concurrency_ranges_min():
    logger.info("test_alpaca_concurrency_ranges_min")
    alpaca_dl = data_api_factory(DataConnectorType.alpaca)

    t = time.time()
    if (
        len(
            alpaca_dl.data_concurrency_ranges(
                symbol="AAPL",
                start=pd.Timestamp("2021-11-10", tz=clock.NY),
                end=pd.Timestamp("2022-01-07", tz=clock.NY),
                scale=TimeScale.minute,
            )
        )
        != 5
    ):
        raise AssertionError("expected 5")
    logger.info("%s", time.time() - t)

    t = time.time()
    if (
        len(
            alpaca_dl.data_concurrency_ranges(
                symbol="AAPL",
                start=pd.Timestamp("2022-01-01", tz=clock.NY),
                end=pd.Timestamp("2022-01-07", tz=clock.NY),
                scale=TimeScale.minute,
            )
        )
        != 2
    ):
        raise AssertionError("expected 2")
    logger.info("%s", time.time() - t)

    return True


@settings(deadline=None, max_examples=100)
@given(
    start=st.dates(min_value=date(2018, 1, 1), max_value=date(2022, 1, 1)),
    end=st.dates(min_value=date(2018, 1, 1), max_value=date(2022, 1, 1)),
)
def test_hpy_alpaca_concurrency_ranges_min(start: date, end: date):
    alpaca_dl = data_api_factory(DataConnectorType.alpaca)

    t = time.time()
    r = alpaca_dl.data_concurrency_ranges(
        symbol="AAPL",
        start=pd.Timestamp(start, tz=clock.NY),
        end=pd.Timestamp(end, tz=clock.NY),
        scale=TimeScale.minute,
    )
    if r.tz != clock.NY:
        raise AssertionError(f"range time zone {r.tz} is not New York")
    duration = time.time() - t

    logger.info("duration=%s, len=%s -> %s", duration, len(r), r)
