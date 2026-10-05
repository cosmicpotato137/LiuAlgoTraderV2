import logging
import uuid

import pytest

from liualgotrader.db.session import create_db_connection
from liualgotrader.strategy.base import Strategy

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


@pytest.mark.asyncio
async def test_get_strategy():
    s = await Strategy.get_strategy(
        batch_id=str(uuid.uuid4()),
        strategy_name="MyStrategy",
        strategy_details={
            "filename": "./examples/skeleton-strategy/my_strategy.py",
            "schedule": [],
        },
    )

    if not s:
        raise AssertionError("Failed to instantiate strategy")

    logger.info("Loaded strategy %s", s.name)

    return True
