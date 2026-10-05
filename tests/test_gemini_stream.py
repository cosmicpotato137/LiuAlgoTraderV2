import asyncio
import logging
import time
from multiprocessing import Queue
from threading import Thread

import pytest

from liualgotrader.common import config
from liualgotrader.common.types import SymbolQueueMap, WSEventType
from liualgotrader.vendors.gemini.streaming import GeminiStream

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.requires_credentials("gemini")

gemini_stream: GeminiStream
queues: SymbolQueueMap
stop: bool = False


@pytest.fixture(autouse=True)
async def stream_setup():
    global gemini_stream
    global queues
    queues = SymbolQueueMap()
    gemini_stream = GeminiStream(queues, config.gemini)


def listener(q: Queue):
    logger.info("start listen %s", q)
    while not stop:
        try:
            d = q.get(timeout=2)
            logger.info("got in q: %s", d)
        except Exception as e:
            logger.info("%s timeout...", e)
            time.sleep(1)

    logger.info("end listen")


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_apple_sec_agg():
    global gemini_stream
    global stop
    await gemini_stream.run()
    logger.info("going to subscribe")
    q = Queue()
    queues["BTCUSD"] = q
    running_task = Thread(
        target=listener,
        args=(q,),
    )
    logger.info("start thread")
    running_task.start()
    logger.info("started")
    await asyncio.sleep(2)

    status = await gemini_stream.subscribe(
        ["BTCUSD"], [WSEventType.MIN_AGG, WSEventType.TRADE]
    )
    logger.info("subscribe result: %s", status)
    if not status:
        raise AssertionError(f"Failed in gemini_stream.subscribe w/ {status}")
    await asyncio.sleep(1 * 60)
    await gemini_stream.close()

    stop = True
    running_task.join()

    return True
