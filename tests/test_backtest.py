import logging
from datetime import date

import pytest

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import AssetType, TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.enhanced_backtest import Backtest
from liualgotrader.strategy.new_base import Context
from liualgotrader.strategy.runtime import RunState
from liualgotrader.strategy.tradeplan import create_strategies, load_tradeplan

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


async def run_backtest(
    scale: TimeScale, from_date: date, to_date: date, lookback_days: int
):
    config.debug_enabled = False
    [spec] = load_tradeplan("./examples/sma_crossover")
    spec["signal"]["lookback_days"] = lookback_days
    ctx = Context(
        DataLoader(scale=scale),
        backtesting=True,
        asset_type=AssetType.US_EQUITIES,
    )
    session = Backtest(ctx, RunState(create_strategies([spec], ctx)), scale)
    await session.simulate_range(from_date, to_date)

    logger.info("trades: %s", session.trades)
    return session


@pytest.mark.asyncio
async def test_backtest_day():
    logger.info("*** test_backtest_day ***")
    await run_backtest(
        TimeScale.day, date(2020, 10, 1), date(2020, 11, 1), lookback_days=60
    )


@pytest.mark.asyncio
async def test_backtest_min():
    logger.info("*** test_backtest_min ***")
    await run_backtest(
        TimeScale.minute,
        date(2020, 10, 1),
        date(2020, 10, 3),
        lookback_days=3,
    )
