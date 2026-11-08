import logging

import pytest

from liualgotrader.common import config
from liualgotrader.common.types import Order, OrderType
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.alpaca.trader import AlpacaTrader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")

alpaca_trader: AlpacaTrader

account_id: str = "f6c9596e-e7ce-4ecc-8ed8-fe6c9720e96a"


@pytest.fixture(autouse=True)
async def db_connection():
    global alpaca_trader
    await create_db_connection()
    alpaca_trader = AlpacaTrader(config.alpaca)


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_sell_apple():
    global alpaca_trader
    global account_id

    try:
        order = await alpaca_trader.submit_order(
            symbol="AAPL",
            qty=2.0,
            side=Order.FillSide.sell,
            order_type=OrderType.MARKET,
            on_behalf_of=account_id,
        )
    except AssertionError as e:
        logger.info("AssertionError with %s", e)
    else:
        logger.info("%s", order)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_buy_apple():
    global alpaca_trader
    global account_id
    try:
        order = await alpaca_trader.submit_order(
            symbol="AAPL",
            qty=2.0,
            side=Order.FillSide.buy,
            order_type=OrderType.MARKET,
            on_behalf_of=account_id,
        )
        logger.info("%s", order)
    except Exception as e:
        logger.info("EXCEPTION: %s", e)

    return True
