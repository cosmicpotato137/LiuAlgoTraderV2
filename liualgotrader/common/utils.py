"""General helpers that are not specific to one part of the package.

Functions
---------
load_class
    Return the class that a specification names.
date_from_string
    Return the date described by a natural-language string.
notify
    Call a callback, and log rather than raise its exceptions.
"""

import hashlib
import importlib
import importlib.util
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

import parsedatetime.parsedatetime as pdt

from liualgotrader.common import clock

logger = logging.getLogger(__name__)

T = TypeVar("T")


def load_class(base: type[T], spec: dict) -> type[T]:
    """Return the class that a specification names.

    Load each file once, under a module name derived from its path, so that
    the classes of one file share its module.

    Parameters
    ----------
    base: type[T]
        The class that the named class must inherit from.
    spec: dict
        The specification, such as a trade plan entry. With a "filename", its
        "class" is the name of a class in that file; otherwise, it is a dotted
        import path such as "liualgotrader.filters.momentum.Momentum". Both
        settings are removed.

    Raises
    ------
    Raise KeyError if spec has no "class", ImportError or AttributeError if
    the class cannot be loaded, and TypeError if it does not inherit from base.
    """
    class_name = spec.pop("class")
    filename = spec.pop("filename", None)
    if filename:
        path = Path(filename).resolve()
        module_name = (
            "liualgotrader_user_"
            + hashlib.sha1(
                str(path).encode(), usedforsecurity=False
            ).hexdigest()
        )
        module = sys.modules.get(module_name)
        if module is None:
            module_spec = importlib.util.spec_from_file_location(
                module_name, path
            )
            if module_spec is None or module_spec.loader is None:
                raise ImportError(f"cannot load {filename}")
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_name] = module
            try:
                module_spec.loader.exec_module(module)
            except BaseException:
                del sys.modules[module_name]
                raise
        loaded_class = getattr(module, class_name)
    else:
        module_path, _, attr = class_name.rpartition(".")
        loaded_class = getattr(importlib.import_module(module_path), attr)

    if not (isinstance(loaded_class, type) and issubclass(loaded_class, base)):
        raise TypeError(f"{class_name} must inherit from {base.__name__}")
    return loaded_class


def date_from_string(s: str) -> date:
    """Return the date described by a natural-language string.

    Parameters
    ----------
    s: str
        The date string, either explicit or relative to the current New York
        time, such as "yesterday".

    Raises
    ------
    Raise ValueError if the string cannot be parsed as a date or a time.
    """
    c = pdt.Calendar()
    result, what = c.parse(s, clock.now().timetuple())
    dt = None

    # what was returned (see http://code-bear.com/code/parsedatetime/docs/)
    # 0 = failed to parse
    # 1 = date (with current time, as a struct_time)
    # 2 = time (with current date, as a struct_time)
    # 3 = datetime
    if what in (1, 2):
        # result is struct_time
        dt = date(*result[:3])
    elif what == 3:
        # result is a datetime
        dt = result.date()

    if dt is None:
        raise ValueError(f"Don't understand date '{s}'")

    return dt


async def notify(callback: Callable[[T], Awaitable[None]], arg: T) -> None:
    """Call a callback, and log rather than raise its exceptions.

    Parameters
    ----------
    callback: Callable[[T], Awaitable[None]]
        The coroutine function to call, such as a rule's on_fill.
    arg: T
        The argument to call it with.
    """
    try:
        await callback(arg)
    except Exception:
        logger.exception("%s failed", callback.__qualname__)
