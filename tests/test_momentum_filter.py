import logging

import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import DataConnectorType
from liualgotrader.data.data_loader import DataLoader
from liualgotrader.db.session import create_db_connection
from liualgotrader.filters.momentum import Momentum
from liualgotrader.strategy.base import Context
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


def momentum(connector: DataConnectorType) -> Momentum:
    return Momentum(
        ctx=Context(DataLoader(connector=connector), trader=trader_factory()),
        max_share_price=500,
        min_share_price=0,
        min_last_dv=3,
        today_change_percent=5,
        min_volume=50000,
        from_market_open=0,
    )


@pytest.mark.asyncio
async def test_filter_alpaca() -> bool:
    logger.info("test_filter_alpaca")

    config.debug_enabled = False
    symbols = await momentum(DataConnectorType.alpaca).run(clock.now())

    logger.info("%s", symbols)
    return True


@pytest.mark.asyncio
async def no_test_filter_polygon() -> bool:
    logger.info("test_filter_polygon")

    config.debug_enabled = True
    symbols = await momentum(DataConnectorType.polygon).run(clock.now())

    logger.info("%s", symbols)
    return True
