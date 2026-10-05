import logging

import pytest

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import DataConnectorType
from liualgotrader.db.session import create_db_connection
from liualgotrader.scanners.momentum import Momentum
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


@pytest.mark.asyncio
async def test_scanner_alpaca() -> bool:
    logger.info("test_scanner_alpaca")

    config.debug_enabled = False
    dl = DataLoader(connector=DataConnectorType.alpaca)
    trader = trader_factory()
    scanner = Momentum(
        recurrence=None,
        target_strategy_name=None,
        data_loader=dl,
        trading_api=trader,
        max_share_price=500,
        min_share_price=0,
        min_last_dv=3,
        today_change_percent=5,
        min_volume=50000,
        from_market_open=0,
    )

    symbols = await scanner.run()

    logger.info("%s", symbols)
    return True


@pytest.mark.asyncio
async def no_test_scanner_polygon() -> bool:
    logger.info("test_scanner_polygon")

    config.debug_enabled = True
    dl = DataLoader(connector=DataConnectorType.polygon)
    trader = trader_factory()
    scanner = Momentum(
        recurrence=None,
        target_strategy_name=None,
        data_loader=dl,
        trading_api=trader,
        max_share_price=500,
        min_share_price=0,
        min_last_dv=3,
        today_change_percent=5,
        min_volume=50000,
        from_market_open=0,
    )

    symbols = await scanner.run()

    logger.info("%s", symbols)
    return True
