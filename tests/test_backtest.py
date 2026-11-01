import logging
from datetime import date

import pytest
import toml

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import AssetType, TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.enhanced_backtest import Backtest
from liualgotrader.strategy.new_base import Context, StrategyGraph

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("alpaca")


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


async def run_backtest(
    scale: TimeScale, from_date: date, to_date: date, lookback_days: int
):
    config.debug_enabled = False
    tradeplan = toml.load("./examples/sma_crossover/tradeplan.toml")
    tradeplan["signals"]["sma_cross"]["lookback_days"] = lookback_days
    ctx = Context(DataLoader(scale=scale), backtesting=True)
    session = Backtest(
        ctx, StrategyGraph.from_tradeplan(tradeplan, ctx), scale
    )
    await session.run(from_date, to_date, AssetType.US_EQUITIES)

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
