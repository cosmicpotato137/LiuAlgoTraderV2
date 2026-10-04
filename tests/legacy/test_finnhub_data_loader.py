import logging
from datetime import date, datetime

import pandas as pd
import pytest
from pytz import timezone

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import DataConnectorType, TimeScale

logger = logging.getLogger(__name__)

nyc = timezone("America/New_York")


@pytest.mark.devtest
def test_create_data_loader_default() -> bool:
    return bool(DataLoader(connector=DataConnectorType.finnhub))


@pytest.mark.devtest
def test_create_data_loader_types() -> bool:
    return all(
        DataLoader(scale=scale, connector=DataConnectorType.finnhub)
        for scale in TimeScale
    )


@pytest.mark.devtest
def test_apple_stock_current_price() -> bool:
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price = dl["AAPL"].close[-1]
    last_price_time = dl["AAPL"].close.index[-1]
    before_price = dl["AAPL"].close[-5]
    before_price_time = dl["AAPL"].close.index[-5]

    logger.info(
        "apple %s @ %s, before was %s@%s",
        last_price,
        last_price_time,
        before_price,
        before_price_time,
    )

    return True


@pytest.mark.devtest
def test_apple_stock_current_price_range_int_minute() -> bool:
    logger.info("test_apple_stock_current_price_range_int_minute")
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[-5:-1]  # type:ignore
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_apple_stock_current_price_range_int_day() -> bool:
    config.data_connector = DataConnectorType.finnhub
    logger.info("test_apple_stock_current_price_range_int_day")
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[-6:-1]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_daily_price() -> bool:
    config.data_connector = DataConnectorType.finnhub
    logger.info("test_apple_stock_daily_price")
    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.finnhub)
    last_price = dl["AAPL"].close[-1]
    last_price_time = dl["AAPL"].close.index[-1]
    before_price = dl["AAPL"].close[-5]
    before_price_time = dl["AAPL"].close.index[-5]
    logger.info(
        "apple %s @ %s, before was %s@%s",
        last_price,
        last_price_time,
        before_price,
        before_price_time,
    )

    return True


@pytest.mark.devtest
def test_negative_current_price() -> bool:
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    try:
        dl["DFGDFGDFG"].close[-1]
    except ValueError:
        return True

    return False


@pytest.mark.devtest
def test_apple_stock_close_price_range_str_day() -> bool:
    config.data_connector = DataConnectorType.finnhub
    logger.info("test_apple_stock_close_price_range_int_day")
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[
        "2021-01-01":"2021-01-05"  # type:ignore
    ]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_close_price_range_str_minute() -> bool:
    config.data_connector = DataConnectorType.finnhub
    logger.info("test_apple_stock_close_price_range_str_minute")
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[
        "2021-01-05 09:45:00":"2021-01-05 09:50:00"  # type:ignore
    ]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_close_price_range_str_minute_int() -> bool:
    logger.info("test_apple_stock_close_price_range_str_minute")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[
        "2021-01-05 09:45:00":-1  # type:ignore
    ]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_close_price_range_int_str_minute() -> bool:
    logger.info("test_apple_stock_close_price_range_str_minute")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].close[
        -5 : str(datetime.now())  # type:ignore
    ]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_int_minute() -> bool:
    logger.info("test_apple_stock_close_price_range_str_minute")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"][-5:-1]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_int_day() -> bool:
    logger.info("test_apple_stock_price_range_int_day")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"][-5:-1]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_day() -> bool:
    logger.info("test_apple_stock_price_range_date_day")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"]["2020-10-05":"2020-10-08"]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_int_day() -> bool:
    logger.info("test_apple_stock_price_range_date_int_day")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"]["2020-10-05":-1]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_int_min() -> bool:
    logger.info("test_apple_stock_price_range_date_int_min")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"]["2020-10-05":-1]  # type:ignore
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_int_min_open() -> bool:
    logger.info("test_apple_stock_price_range_date_int_min_open")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"]["2020-10-05":]  # type:ignore
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_apple_stock_price_open_range_date_int_min_open() -> bool:
    logger.info("test_apple_stock_price_close_range_date_int_min_open")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    last_price_range = dl["AAPL"].open["2020-10-05":]  # type:ignore
    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_min_open() -> bool:
    logger.info("test_apple_stock_price_range_date_min_open")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    try:
        last_price_range = dl["AAPL"][:]  # type:ignore
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True


@pytest.mark.devtest
def test_apple_stock_price_open_range_date_min_open() -> bool:
    logger.info("test_apple_stock_price_open_range_date_min_open")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    try:
        last_price_range = dl["AAPL"].open[:]  # type:ignore
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_min() -> bool:
    logger.info("test_apple_stock_price_range_date_min")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    d2 = date(year=2021, month=2, day=2)
    last_price_range = dl["AAPL"][d1:d2].between_time(  # type:ignore
        "9:30", "16:00"
    )  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_min_mixed() -> bool:
    logger.info("test_apple_stock_price_range_date_min_mixed")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    last_price_range = dl["AAPL"][d1:"2021-02-02"].between_time(  # type:ignore
        "9:30", "16:00"
    )  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_range_date_day_mixed() -> bool:
    logger.info("test_apple_stock_price_range_date_day_mixed")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.day, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    last_price_range = dl["AAPL"][d1:"2021-02-02"]  # type:ignore
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_open_range_date_min_mixed() -> bool:
    logger.info("test_apple_stock_price_range_date_min_mixed")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    last_price_range = (
        dl["AAPL"]
        .open[d1:"2021-02-02"]  # type:ignore
        .between_time("9:30", "16:00")  # type:ignore
    )
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_open_str() -> bool:
    logger.info("test_apple_stock_price_open_str")
    config.data_connector = DataConnectorType.finnhub
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    last_price_range = dl["AAPL"].open["2021-02-02 09:45:00"]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_apple_stock_price_open_date() -> bool:
    logger.info("test_apple_stock_price_open_date")
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    last_price_range = dl["AAPL"].open[d1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
def test_get_symbols_finnhub() -> bool:
    logger.info("test_get_symbols_finnhub")
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    tickers = dl.data_api.get_symbols()
    logger.info("%s", len(tickers))

    return True


@pytest.mark.devtest
def test_apple_update() -> bool:
    logger.info("test_apple_stock_price_open_str")
    dl = DataLoader(TimeScale.minute, DataConnectorType.finnhub)
    d1 = date(year=2021, month=2, day=1)
    dl["AAPL"][-1]
    logger.info("after this")
    dl["AAPL"].loc["2021-02-02 09:46:00"] = [
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
    ]
    logger.info("%s", dl["AAPL"].loc["2021-02-02 09:46:00"])

    return True
