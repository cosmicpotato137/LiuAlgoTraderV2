import asyncio
from multiprocessing import Queue

import pytest

from liualgotrader.common import config
from liualgotrader.common.types import SymbolQueueMap
from liualgotrader.stream.base import WSEventType
from liualgotrader.vendors.alpaca.trader import AlpacaTrader
from liualgotrader.vendors.polygon.streaming import PolygonStream

queues: SymbolQueueMap
polygon_stream: PolygonStream


@pytest.fixture
def event_loop():
    global polygon_stream
    global queues
    loop = asyncio.new_event_loop()
    queues = SymbolQueueMap()
    polygon_stream = PolygonStream(queues, config.polygon)
    yield loop
    loop.close()


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_apple_sec_agg():
    global polygon_stream
    global queues

    queues["AAPL"] = Queue()
    queues["GLD"] = Queue()
    apple = await polygon_stream.subscribe(
        ["AAPL", "GLD"], [WSEventType.SEC_AGG]
    )
    apple = await polygon_stream.subscribe(
        ["AAPL", "GLD"], [WSEventType.MIN_AGG]
    )
    print(apple)
    await asyncio.sleep(1 * 60)

    print("done")
    await polygon_stream.close()

    return True
