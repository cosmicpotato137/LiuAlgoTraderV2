import asyncio
import logging
import time
from multiprocessing import Queue
from threading import Thread

import pytest

from liualgotrader.common import config
from liualgotrader.common.types import SymbolQueueMap, WSEventType
from liualgotrader.vendors.alpaca.streaming import AlpacaStream

logger = logging.getLogger(__name__)

stop: bool = False


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
async def test_crypto_stream():
    global stop
    queues = SymbolQueueMap()
    alpaca_stream = AlpacaStream(queues, config.alpaca)
    await alpaca_stream.run()

    logger.info("going to subscribe")
    queues["BTCUSD"] = Queue()
    running_task = Thread(
        target=listener,
        args=(queues["BTCUSD"],),
    )
    logger.info("start listen thread")
    running_task.start()
    logger.info("started")

    await asyncio.sleep(2)
    status = await alpaca_stream.subscribe(
        ["BTCUSD"],
        [WSEventType.MIN_AGG, WSEventType.TRADE, WSEventType.QUOTE],
    )
    logger.info("subscribe result: %s", status)
    if not status:
        raise AssertionError(f"Failed in alpaca_stream.subscribe w/ {status}")
    await asyncio.sleep(1 * 60)
    await alpaca_stream.close()

    tasks = asyncio.all_tasks()
    for t in tasks:
        if not t.done():
            logger.info("%s", t)

    stop = True
    running_task.join()

    return True
