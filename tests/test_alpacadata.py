import logging

import pytest

from liualgotrader.common import clock, config
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.alpaca.data import AlpacaData

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


def test_get_trading_day():
    alpaca_data = AlpacaData(config.alpaca)

    symbol = "BTCUSD"
    last_trading_time = alpaca_data.get_last_trading(symbol)

    logger.info("%s last trading time: %s", symbol, last_trading_time)
    trading_day = alpaca_data.get_trading_day(symbol, last_trading_time, -1500)

    logger.info("%s trading day: %s", symbol, trading_day)
    if trading_day.tz != clock.NY:
        raise AssertionError(f"time zone {trading_day.tz} is not New York")
