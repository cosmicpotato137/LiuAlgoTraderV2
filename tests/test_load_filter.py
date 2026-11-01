import logging

import pytest

from liualgotrader.strategy.new_base import Context, create_filters

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_create_filters():
    tradeplan = {
        "filters": {
            "mine": {
                "class": "MyFilter",
                "filename": "./examples/sma_crossover/filter.py",
                "recurrence": 5,
            }
        }
    }
    filters = create_filters(tradeplan, Context(None))

    f = filters["mine"]
    if f.name != "mine" or f.recurrence.total_seconds() != 300:
        raise AssertionError(f"unexpected filter {f!r} {f.recurrence}")
    if await f.run(None) != ["AAPL"]:
        raise AssertionError("unexpected symbols")
    if "class" not in tradeplan["filters"]["mine"]:
        raise AssertionError("create_filters modified the trade plan")

    logger.info("Loaded filter %s", f)
