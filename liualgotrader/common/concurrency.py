"""Size the consumer pool and provide the event loop for synchronous code.

Functions
---------
calc_num_consumer_processes
    Return how many consumer processes to launch.
reset_event_loop
    Close the current thread's event loop and return a new current one.
get_event_loop
    Return the current thread's event loop, creating one if needed.
"""

import asyncio
import logging

import psutil

from liualgotrader.common import config

logger = logging.getLogger(__name__)

# The most consumer processes to launch per idle physical core.
_PROCESSES_PER_CORE = 5.0


def calc_num_consumer_processes() -> int:
    """Return the number of consumer processes to launch.

    Use config.num_consumers when it is positive, and log a warning if it is
    more than _PROCESSES_PER_CORE per physical core, the most that the
    derived count can be. Otherwise, derive the count from the physical cores
    and the idle CPU fraction, blocking for five seconds to sample the load,
    or return 1 if the core count is unknown.

    Returns
    -------
    Return at least 1.
    """
    num_cpu = psutil.cpu_count(False)

    if config.num_consumers > 0:
        if num_cpu and config.num_consumers > _PROCESSES_PER_CORE * num_cpu:
            logger.warning(
                "NUM_CONSUMERS=%s is more than %s consumer processes per "
                "physical core (%s cores)",
                config.num_consumers,
                _PROCESSES_PER_CORE,
                num_cpu,
            )
        return config.num_consumers

    if not num_cpu:
        logger.info(
            "Can't automatically detect number of CPUs, use fixed configuration"
        )
        return 1

    load_pct: float = psutil.cpu_percent(interval=5)

    logger.info("Total CPU Load:%s, num_cpu:%s", load_pct, num_cpu)

    return max(1, int(_PROCESSES_PER_CORE * (1 - load_pct / 100.0) * num_cpu))


def reset_event_loop() -> asyncio.AbstractEventLoop:
    """Close the current thread's event loop and return a new current one.

    Set the new loop as the current loop, so later calls to get_event_loop in
    the same thread return it. Do not call it from asynchronous code.
    """
    get_event_loop().close()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def get_event_loop() -> asyncio.AbstractEventLoop:
    """Return the current thread's event loop, creating one if needed.

    Set a newly created loop as the current loop, so later calls in the same
    thread return it. Replace the current loop if it is closed. Do not call it
    from asynchronous code.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop
