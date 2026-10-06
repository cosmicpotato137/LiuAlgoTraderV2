import logging
from datetime import date

import pandas as pd
import pytest
from alpaca.data.timeframe import TimeFrame

from liualgotrader.common import clock, config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.vendors.alpaca.data import AlpacaData
from liualgotrader.vendors.alpaca.streaming import AlpacaStream

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")

may_1 = pd.Timestamp("2021-05-01", tz=clock.NY)
oct_1 = pd.Timestamp("2021-10-01", tz=clock.NY)


@pytest.mark.devtest
def test_crypto_get_symbol() -> bool:
    alpaca_data = AlpacaData(config.alpaca)

    start = date(2021, 5, 1)
    end = date(2021, 10, 1)
    _start, _end = alpaca_data._localize_start_end(start, end)
    df = alpaca_data._crypto_get_symbol_data(
        symbol="BTCUSD", start=_start, end=_end, timeframe=TimeFrame.Day
    )
    if not df.empty and df.index.tz != clock.NY:
        raise AssertionError(f"index time zone {df.index.tz} is not New York")
    logger.info("%s", df)
    return True


@pytest.mark.devtest
def test_btc_data_loader_day() -> bool:
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.alpaca)

    data = dl["BTCUSD"][may_1:oct_1]  # type: ignore
    logger.info("%s", data)
    return True


@pytest.mark.devtest
def test_btc_data_loader_min() -> bool:
    dl = DataLoader(connector=DataConnectorType.alpaca)

    data = dl["BTCUSD"][may_1:oct_1]  # type: ignore
    logger.info("%s", data)
    return True


@pytest.mark.devtest
def test_eth_data_loader_day() -> bool:
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.alpaca)

    data = dl["ETH/USD"][may_1:oct_1]  # type: ignore
    logger.info("%s", data)
    return True


@pytest.mark.devtest
def test_eth_data_loader_minute_offset() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    data = dl["ETH/USD"][-1500:]  # type: ignore
    logger.info("%s %s", len(data), data)
    return True


def eth_minute_bars(start: pd.Timestamp, end: pd.Timestamp) -> int:
    # Alpaca has no bar for a minute without trades, so the length a loader
    # should return depends on the vendor data rather than on the range.
    return len(
        AlpacaData(config.alpaca)._crypto_get_symbol_data(
            symbol="ETH/USD",
            start=start,
            end=end,
            timeframe=TimeFrame.Minute,
        )
    )


@pytest.mark.devtest
def test_eth_data_loader_length() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    end = pd.Timestamp("2022-07-28 21:20", tz=clock.NY)
    logger.info("end: %s", end)
    data = dl["ETH/USD"][end - pd.Timedelta(minutes=1500) : end]  # type: ignore

    expected = eth_minute_bars(end - pd.Timedelta(minutes=1500), end)
    if len(data) != expected:
        raise AssertionError(f"Data length {len(data)} is not {expected}")

    logger.info("%s %s", len(data), data)
    return True


@pytest.mark.devtest
def test_eth_data_loader_length2() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)

    end = pd.Timestamp("2022-07-28 21:20", tz=clock.NY)
    logger.info("end: %s", end)

    data = dl["ETH/USD"][end - pd.Timedelta(minutes=2000) : end - pd.Timedelta(minutes=100)]  # type: ignore

    data = dl["ETH/USD"][end - pd.Timedelta(minutes=1500) : end]  # type: ignore

    expected = eth_minute_bars(end - pd.Timedelta(minutes=1500), end)
    if len(data) != expected:
        raise AssertionError(f"Data length {len(data)} is not {expected}")

    logger.info("%s %s", len(data), data)
    return True


@pytest.mark.devtest
def test_eth_data_loader_day_offset() -> bool:
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.alpaca)

    data = dl["ETH/USD"][-1500:]  # type: ignore
    logger.info("%s %s", len(data), data)
    return True
