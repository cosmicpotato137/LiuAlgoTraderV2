import logging
from datetime import date

import pandas as pd
import pytest

from liualgotrader.common import config
from liualgotrader.common.types import (SymbolQueueMap, TimeScale, WSConnectState,
                                        WSEventType)
from liualgotrader.vendors.polygon.data import PolygonData

logger = logging.getLogger(__name__)


@pytest.mark.devtest
def test_polygon_aapl_data_day() -> bool:
    polygon = PolygonData(config.polygon)
    logger.info(
        "%s",
        polygon.get_symbol_data(
            "AAPL",
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
            scale=TimeScale.day,
        ),
    )
    return True


@pytest.mark.devtest
def test_polygon_aapl_data_min() -> bool:
    polygon = PolygonData(config.polygon)
    logger.info(
        "%s",
        polygon.get_symbol_data(
            "AAPL",
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
        ).between_time("9:30", "16:00"),
    )
    return True


@pytest.mark.devtest
def test_polygon_get_symbols() -> bool:
    polygon = PolygonData(config.polygon)
    symbols = polygon.get_symbols()
    logger.info("%s symbols are retrieved from Polygon", len(symbols))
    return True


# this test may fail if your Polygon account is not in premium plan
@pytest.mark.devtest
def test_polygon_get_market_snapshot() -> bool:
    polygon = PolygonData(config.polygon)
    market_snapshots = polygon.get_market_snapshot()
    logger.info(
        "%s tickers of market snapshots are retrieved from Polygon",
        len(market_snapshots),
    )
    return True
