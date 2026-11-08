import logging

import pandas as pd
import pytest

from liualgotrader.common import clock
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.data.data_loader import DataLoader

logger = logging.getLogger(__name__)


def days_ago(days: int) -> pd.Timestamp:
    """Return midnight in New York a number of days before today."""
    return pd.Timestamp(clock.today() - pd.Timedelta(days=days), tz=clock.NY)


@pytest.mark.devtest
def test_create_data_loader_default() -> bool:
    return bool(DataLoader(connector=DataConnectorType.gemini))


@pytest.mark.devtest
def test_ethusd_stock_daily_price() -> bool:
    logger.info("test_ethusd_stock_daily_price")
    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.gemini)
    last_price = dl["ETHUSD"].close[-1]

    last_price_time = dl["ETHUSD"].close.index[-1]
    logger.info("%s %s", last_price, last_price_time)
    before_price = dl["ETHUSD"].close[-3]

    logger.info("%s", dl["ETHUSD"])
    logger.info(
        "ETH/USD %s @ %s, before was %s",
        last_price,
        last_price_time,
        before_price,
    )

    return True


@pytest.mark.devtest
def test_btc_current_price() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price = dl["BTCUSD"].close[-1]
    last_price_time = dl["BTCUSD"].close.index[-1]
    before_price = dl["BTCUSD"].close[-5]
    before_price_time = dl["BTCUSD"].close.index[-5]

    logger.info(
        "BTCUSD %s @ %s, before was %s@%s",
        last_price,
        last_price_time,
        before_price,
        before_price_time,
    )

    return True


@pytest.mark.devtest
def test_stock_current_price_range_int_minute() -> bool:
    logger.info("test_stock_current_price_range_int_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].close[-5:-1]
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_negative_current_price() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    try:
        dl["DFGDFGDFG"].close[-1]
    except ValueError:
        return True

    return False


@pytest.mark.devtest
def test_stock_close_price_range_str_day() -> bool:
    logger.info("test_stock_close_price_range_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].close[days_ago(4) : days_ago(2)]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_close_price_range_str_minute() -> bool:
    logger.info("test_stock_close_price_range_str_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].close[
        days_ago(20)
        .replace(hour=10, minute=5) : days_ago(20)
        .replace(hour=10, minute=5)
    ]

    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_close_price_range_str_minute_int() -> bool:
    logger.info("test_stock_close_price_range_str_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].close[
        days_ago(2).replace(hour=10, minute=5) : -1
    ]

    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_int_minute() -> bool:
    logger.info("test_stock_close_price_range_str_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][-5:-1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_int_day() -> bool:
    logger.info("test_stock_price_range_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][-5:-1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_date_day() -> bool:
    logger.info("test_stock_price_range_date_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][days_ago(4) : days_ago(2)]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_date_int_day() -> bool:
    logger.info("test_stock_price_range_date_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][days_ago(3) : -1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_date_int_min() -> bool:
    logger.info("test_stock_price_range_date_int_min")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][
        days_ago(2).replace(hour=10, minute=5) : -1
    ]
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_stock_price_range_date_int_min_open() -> bool:
    logger.info("test_stock_price_range_date_int_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"][days_ago(2) :]
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_stock_price_open_range_date_int_min_open() -> bool:
    logger.info("test_stock_price_close_range_date_int_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].open[days_ago(2) :]
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_stock_price_range_date_min_open() -> bool:
    logger.info("test_stock_price_range_date_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    try:
        last_price_range = dl["ETHUSD"][:]
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True


@pytest.mark.devtest
def test_stock_price_open_range_date_min_open() -> bool:
    logger.info("test_stock_price_open_range_date_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    try:
        last_price_range = dl["BTCUSD"].open[:]
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True


@pytest.mark.devtest
def test_stock_price_range_date_min() -> bool:
    logger.info("test_stock_price_range_date_min")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"][days_ago(10) : days_ago(9)].between_time(
        "9:30", "16:00"
    )
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_date_min_mixed() -> bool:
    logger.info("test_stock_price_range_date_min_mixed")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["ETHUSD"][days_ago(4) : days_ago(2)].between_time(
        "9:30", "16:00"
    )
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_range_date_day_mixed() -> bool:
    logger.info("test_stock_price_range_date_day_mixed")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.gemini)

    last_price_range = dl["BTCUSD"][days_ago(3) : days_ago(0)]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_open_range_date_min_mixed() -> bool:
    logger.info("test_stock_price_range_date_min_mixed")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = (
        dl["ETHUSD"]
        .open[days_ago(4) : days_ago(2)]
        .between_time("9:30", "16:00")
    )
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_open_str() -> bool:
    logger.info("test_stock_price_open_str")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].open[
        days_ago(20).replace(hour=10, minute=5)
    ]

    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_stock_price_open_date() -> bool:
    logger.info("test_stock_price_open_date")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    last_price_range = dl["BTCUSD"].open[days_ago(20)]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_get_symbols_alpaca() -> bool:
    logger.info("test_get_symbols_gemini")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    tickers = dl.data_api.get_symbols()
    logger.info("%s", len(tickers))

    return True


@pytest.mark.devtest
def test_stock_price_open_str2() -> bool:
    logger.info("test_stock_price_open_str2")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.gemini)
    when = days_ago(20).replace(hour=10, minute=5)
    dl["BTCUSD"][-1]
    logger.info("after this")
    dl["BTCUSD"].loc[when] = [
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
    ]

    logger.info("%s", dl["BTCUSD"].loc[when])

    return True
