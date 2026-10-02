"""Framework logging, optionally forwarded to Google Cloud Logging.

Functions
---------
tlog
    Log a message tagged with its origin, process ID and time.
tlog_exception
    Log the exception being handled, with its traceback.
"""

import functools
import os
import sys
import traceback
from datetime import datetime


@functools.cache
def _gcp_logger():
    """Return the Google Cloud logger, or None if gcp_logger is disabled.

    Also return None if the logger cannot be created.
    """
    # config is imported on first use, since it imports the data providers,
    # which import this module
    try:
        from liualgotrader.common.config import gcp_logger

        if gcp_logger:
            from google.cloud import logging

            return logging.Client().logger("trader")
    except Exception:
        pass
    return None


def tlog(msg: str, origin: str = None) -> None:
    """Log a message tagged with its origin, process ID and time.

    Print the message to standard output and, when gcp_logger is enabled, send
    it to Google Cloud Logging. Report a cloud logging failure on standard
    output instead of raising.

    Parameters
    ----------
    msg: str
        The message text.
    origin: str, default None
        The tag to prefix, or None for the caller's function name.
    """
    try:
        calling_fn = origin or f"[{sys._getframe(1).f_code.co_name}()]"
    except Exception:
        calling_fn = ""

    if logger := _gcp_logger():
        try:
            logger.log_text(f"{calling_fn}[{os.getpid()}] {msg}")
        except Exception as e:
            print(f"[Error] exception when trying to log to Stackdriver {e}")
    print(f"{calling_fn}[{os.getpid()}]{datetime.now()}:{msg}", flush=True)


def tlog_exception(origin: str):
    """Log the exception being handled, together with its traceback.

    Also print the traceback to standard error. Use only within an exception
    handler.

    Parameters
    ----------
    origin: str
        The tag to prefix each logged line.
    """
    traceback.print_exc()
    exc_info = sys.exc_info()
    lines = traceback.format_exception(*exc_info)
    for line in lines:
        tlog(f"{line}", origin)
    del exc_info
