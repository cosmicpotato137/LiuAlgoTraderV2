import logging
import time
from datetime import date
from typing import List, cast

import pandas as pd
import pytest

from liualgotrader.common import config
from liualgotrader.common.types import TimeScale
from liualgotrader.vendors.alpaca.data import AlpacaData

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


@pytest.mark.devtest
def test_alpaca_aapl_data_day() -> bool:
    alpaca = AlpacaData(config.alpaca)
    logger.info(
        "%s",
        alpaca.get_symbol_data(
            "AAPL",
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
            scale=TimeScale.day,
        ),
    )
    return True


@pytest.mark.devtest
def test_alpaca_aapl_data_min() -> bool:
    alpaca = AlpacaData(config.alpaca)
    logger.info(
        "%s",
        alpaca.get_symbol_data(
            "AAPL",
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
        ).between_time("9:30", "16:00"),
    )
    return True


@pytest.mark.devtest
def test_alpaca_get_symbols() -> bool:
    alpaca = AlpacaData(config.alpaca)

    t0 = time.time()
    symbols = alpaca.get_symbols()
    t1 = time.time()
    logger.info(
        "%s symbols are retrieved from Alpaca in %s seconds",
        len(symbols),
        t1 - t0,
    )
    return True


@pytest.mark.asyncio
async def test_alpaca_get_market_snapshot() -> bool:
    alpaca = AlpacaData(config.alpaca)

    t0 = time.time()
    market_snapshots = await alpaca.get_market_snapshot()
    t1 = time.time()
    logger.info(
        "%s tickers of market snapshots are retrieved from Alpaca in %s seconds",
        len(market_snapshots),
        t1 - t0,
    )
    return True


@pytest.mark.devtest
def test_alpaca_multi_symbols_min() -> bool:
    alpaca = AlpacaData(config.alpaca)
    logger.info(
        "%s",
        alpaca.get_symbols_data(
            ["AAPL", "IBM"],
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
        ),
    )
    return True


@pytest.mark.devtest
def test_alpaca_multi_symbols_day() -> bool:
    alpaca = AlpacaData(config.alpaca)
    logger.info(
        "%s",
        alpaca.get_symbols_data(
            ["AAPL", "IBM"],
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
            TimeScale.day,
        ),
    )
    return True


@pytest.mark.devtest
def test_alpaca_multi_symbols_min_negative() -> bool:
    try:
        AlpacaData(config.alpaca).get_symbols_data(
            cast(List[str], "AAPL"),  # deliberately not a list
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
        )
    except AssertionError:
        return True

    raise AssertionError("excepted an error")
