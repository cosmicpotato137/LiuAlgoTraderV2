import logging
from datetime import date

import pytest

from liualgotrader.db.session import create_db_connection
from liualgotrader.trade.factory import trader_factory

logger = logging.getLogger(__name__)


@pytest.mark.devtest
def test_trader_calendar() -> bool:
    trader = trader_factory()

    td = trader.get_trading_days(start_date=date(year=2021, month=1, day=1))
    logger.info("%s", td)
    return True
