import logging

import pytest

from liualgotrader.common import config
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.alpaca.trader import AlpacaTrader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")

alpaca_trader: AlpacaTrader


@pytest.fixture(autouse=True)
async def db_connection():
    global alpaca_trader
    await create_db_connection()
    alpaca_trader = AlpacaTrader(config.alpaca)


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_symbols():
    global alpaca_trader
    assets = await alpaca_trader.get_tradeable_symbols()
    logger.info("%s", assets)
    logger.info("%s", len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_shortable_symbols():
    global alpaca_trader
    assets = await alpaca_trader.get_shortable_symbols()
    logger.info("%s", assets)
    logger.info("%s", len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_is_fractionable():
    global alpaca_trader
    apa_fractionable = await alpaca_trader.is_fractionable("APA")
    logger.info("APA: %s", apa_fractionable)

    if not apa_fractionable:
        logger.info("APA is not fractionable")
    aapl_fractionable = await alpaca_trader.is_fractionable("AAPL")
    logger.info("AAPL: %s", aapl_fractionable)
    if not aapl_fractionable:
        logger.info("AAPL is fractionable ")

    return True
