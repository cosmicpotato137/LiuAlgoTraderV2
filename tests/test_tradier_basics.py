import logging
from datetime import date, timedelta

import pytest

from liualgotrader.common import config
from liualgotrader.common.types import TimeScale
from liualgotrader.vendors.tradier.data import TradierData

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("tradier")


@pytest.mark.devtest
def test_tradier_aapl_data_day() -> bool:
    tradier = TradierData(config.tradier)
    logger.info(
        "%s",
        tradier.get_symbol_data(
            "AAPL",
            date(year=2021, month=2, day=1),
            date(year=2021, month=2, day=2),
            scale=TimeScale.day,
        ),
    )
    return True


@pytest.mark.devtest
def test_tradier_aapl_data_min() -> bool:
    tradier = TradierData(config.tradier)
    logger.info(
        "%s",
        tradier.get_symbol_data(
            "AAPL",
            start=date.today() - timedelta(days=10),
            end=date.today() - timedelta(days=1),
            scale=TimeScale.minute,
        ),
    )
    return True
