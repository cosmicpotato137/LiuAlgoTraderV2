import logging

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.db.models.tradeplan import TradePlan
from liualgotrader.db.session import create_db_connection

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def db_connection():
    config.build_label = "pytest"
    await create_db_connection()


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_load_trade_plan_from_db():
    trade_plan = await TradePlan.load()

    for plan in trade_plan:
        logger.info("%s", plan)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_new_entries():
    trade_plan = await TradePlan.get_new_entries(
        since=clock.now() - pd.Timedelta(days=5)
    )

    for plan in trade_plan:
        logger.info("%s", plan)

    return True
