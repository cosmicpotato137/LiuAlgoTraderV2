"""Logging set-up for the framework's processes.

Functions
---------
configure_logging
    Send log records from all loggers to standard output.
"""

import logging
import sys
from typing import Optional

from liualgotrader.common import config


def configure_logging(level: Optional[str] = None) -> None:
    """Send log records from all loggers to standard output.

    Tag each record with its time, process ID, level, logger and function.
    Replace any handlers already set on the root logger. Call at the start of
    each process, since spawned processes do not inherit the configuration.

    Parameters
    ----------
    level: Optional[str], default None
        The minimum level to log, such as "DEBUG", or None for
        config.log_level.
    """
    logging.basicConfig(
        level=level or config.log_level,
        format=(
            "%(asctime)s [%(process)d] %(levelname)s "
            "%(name)s.%(funcName)s(): %(message)s"
        ),
        stream=sys.stdout,
        force=True,
    )
