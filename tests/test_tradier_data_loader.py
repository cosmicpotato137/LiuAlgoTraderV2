import logging

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import DataConnectorType, TimeScale
from liualgotrader.data.data_loader import DataLoader

logger = logging.getLogger(__name__)


@pytest.mark.devtest
def test_create_data_loader_default() -> bool:
    return bool(DataLoader(connector=DataConnectorType.tradier))


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_latest_price() -> bool:
    logger.info("test_apple_stock_latest_price")

    logger.info("**** TRADIER ****")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    last_price = dl["AAPL"].close[-1]
    last_price_time = dl["AAPL"].close.index[-1]

    # logger.info("%s", dl["AAPL"])
    logger.info("apple %s @ %s", last_price, last_price_time)

    logger.info("**** ALPACA ****")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.alpaca)
    last_price = dl["AAPL"].close[-1]
    last_price_time = dl["AAPL"].close.index[-1]

    logger.info("apple %s @ %s", last_price, last_price_time)

    # logger.info("**** POLYGON ****")
    # dl = DataLoader(TimeScale.minute, connector=DataConnectorType.polygon)
    # last_price = dl["AAPL"].close[-1]
    # last_price_time = dl["AAPL"].close.index[-1]

    # logger.info("apple %s @ %s", last_price, last_price_time)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_current_price() -> bool:
    logger.info("test_apple_stock_current_price")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
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
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_current_price_range_int_minute() -> bool:
    logger.info("test_apple_stock_current_price_range_int_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"].close[-5:-1]

    logger.info("%s", last_price_range)
    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_current_price_range_int_day() -> bool:
    logger.info("test_apple_stock_current_price_range_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"].close[-6:-1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_day_num_data_points() -> bool:
    logger.info("test_day_num_data_points")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    data = dl["AAPL"].close[-90:]

    if len(data) != 90:
        raise AssertionError(
            f"expected 90 datapoints, received only {len(data)}"
        )

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_day_num_data_points_w_date() -> bool:
    logger.info("test_day_num_data_points")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    data = dl["AAPL"].close[
        -90 : pd.Timestamp("2021-09-10 09:30", tz=clock.NY)
    ]

    if len(data) != 90:
        raise AssertionError(
            f"expected 90 datapoints, received only {len(data)}"
        )

    return True


@pytest.mark.devtest
def no_test_apple_stock_daily_price() -> bool:
    logger.info("test_apple_stock_daily_price")
    dl = DataLoader(scale=TimeScale.day, connector=DataConnectorType.tradier)
    last_price = dl["AAPL"].close[-1]
    last_price_time = dl["AAPL"].close.index[-1]
    logger.info("%s %s", last_price, last_price_time)
    before_price = dl["AAPL"].close[-5]
    logger.info("before_price %s, %s", before_price, dl["AAPL"])
    logger.info(
        "apple %s @ %s, before was %s",
        last_price,
        last_price_time,
        before_price,
    )

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_negative_current_price() -> bool:
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    try:
        dl["DFGDFGDFG"].close[-1]
    except ValueError:
        return True

    return False


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_close_price_range_str_day() -> bool:
    logger.info("test_apple_stock_close_price_range_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"].close[
        pd.Timestamp("2021-01-01", tz=clock.NY) : pd.Timestamp(
            "2021-01-05", tz=clock.NY
        )
    ]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_range_int_minute() -> bool:
    logger.info("test_apple_stock_price_range_int_minute")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"][-5:-1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_range_int_day() -> bool:
    logger.info("test_apple_stock_price_range_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"][-5:-1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_range_date_day() -> bool:
    logger.info("test_apple_stock_price_range_date_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"][
        pd.Timestamp("2020-10-05", tz=clock.NY) : pd.Timestamp(
            "2020-10-08", tz=clock.NY
        )
    ]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_range_date_int_day() -> bool:
    logger.info("test_apple_stock_price_range_date_int_day")
    dl = DataLoader(TimeScale.day, connector=DataConnectorType.tradier)
    last_price_range = dl["AAPL"][pd.Timestamp("2020-10-05", tz=clock.NY) : -1]
    logger.info("%s", last_price_range)

    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_range_date_min_open() -> bool:
    logger.info("test_apple_stock_price_range_date_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    try:
        last_price_range = dl["AAPL"][:]
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True


@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
def test_apple_stock_price_open_range_date_min_open() -> bool:
    logger.info("test_apple_stock_price_open_range_date_min_open")
    dl = DataLoader(TimeScale.minute, connector=DataConnectorType.tradier)
    try:
        last_price_range = dl["AAPL"].open[:]
        logger.info("%s", last_price_range)
    except ValueError:
        return True
    return True
