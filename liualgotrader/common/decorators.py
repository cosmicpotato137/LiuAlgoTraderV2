"""Decorators that instrument function execution.

Functions
---------
timeit
    Wrap a function so that its execution time is logged.
"""

import inspect
import logging
import time

from liualgotrader.common import config

logger = logging.getLogger(__name__)


def timeit(func):
    """Wrap a function so that its execution time is logged.

    Parameters
    ----------
    func
        The function or coroutine function to wrap.

    Returns
    -------
    Return a coroutine function, which must be awaited even when func is
    synchronous.
    """
    async def process(func, *args, **params):
        """Return the result of func, awaiting it if it is a coroutine.

        Parameters
        ----------
        func
            The function or coroutine function.
        *args
            Positional arguments for func.
        **params
            Keyword arguments for func.
        """
        if inspect.iscoroutinefunction(func):
            return await func(*args, **params)
        else:
            return func(*args, **params)

    async def helper(*args, **params):
        """Run the wrapped function, log its duration and return its result.

        Parameters
        ----------
        *args
            Positional arguments for the wrapped function.
        **params
            Keyword arguments for the wrapped function.
        """
        logger.info("%s started", func.__name__)
        start = time.time()
        result = await process(func, *args, **params)
        logger.info(
            "%s >>> %s seconds", func.__name__, round(time.time() - start, 3)
        )
        return result

    return helper
