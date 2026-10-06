import logging

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import TimeScale
from liualgotrader.vendors.gemini.data import GeminiData

logger = logging.getLogger(__name__)


@pytest.mark.devtest
def test_gemini_data_day() -> bool:
    gemini = GeminiData(config.gemini)
    from_date = clock.today() - pd.Timedelta(days=25)
    to_date = from_date + pd.Timedelta(days=1)
    logger.info(
        "%s",
        gemini.get_symbol_data(
            "BTCUSD",
            from_date,
            to_date,
            scale=TimeScale.day,
        ),
    )
    return True


@pytest.mark.devtest
def test_gemini_data_min() -> bool:
    gemini = GeminiData(config.gemini)
    from_date = clock.today() - pd.Timedelta(days=25)
    to_date = from_date + pd.Timedelta(days=1)
    logger.info(
        "%s",
        gemini.get_symbol_data(
            "BTCUSD",
            from_date,
            to_date,
            scale=TimeScale.minute,
        ),
    )
    return True
