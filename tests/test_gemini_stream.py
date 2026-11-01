import asyncio
import logging
from multiprocessing import Queue
from queue import Empty

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.types import (QueueMessageType, SymbolQueueMap,
                                        WSEventType)
from liualgotrader.vendors.gemini.streaming import GeminiStream

logger = logging.getLogger(__name__)

# The (symbol, EV) pairs of the events the test waits for.
EXPECTED = {
    ("btcusd", QueueMessageType.MINUTE_BAR),
    ("ethusd", QueueMessageType.MINUTE_BAR),
    ("btcusd", QueueMessageType.TRADE),
}


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_trades_and_minute_bars():
    queues = SymbolQueueMap()
    btc, eth = Queue(), Queue()
    queues["btcusd"] = btc
    queues["ethusd"] = eth
    gemini_stream = GeminiStream(queues, config.gemini)
    await gemini_stream.run()
    try:
        if not await gemini_stream.subscribe(
            ["BTCUSD", "ethusd"], [WSEventType.MIN_AGG, WSEventType.TRADE]
        ):
            raise AssertionError("subscribe failed")

        # A minute bar arrives as each minute closes, so wait past one.
        seen = set()
        deadline = clock.now() + pd.Timedelta(seconds=90)
        while clock.now() < deadline and not EXPECTED <= seen:
            for q in (btc, eth):
                try:
                    event = q.get_nowait()
                except Empty:
                    continue
                logger.info("got %s", event)
                if event["timestamp"].tz != clock.NY:
                    raise AssertionError(f"not in New York time: {event}")
                seen.add((event["symbol"], event["EV"]))
            await asyncio.sleep(0.1)
    finally:
        await gemini_stream.close()

    if missing := EXPECTED - seen:
        raise AssertionError(f"no events of kind (symbol, EV) {missing}")
