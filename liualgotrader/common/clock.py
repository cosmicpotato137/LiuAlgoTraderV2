"""Time zone and current time of the package.

Every moment in time in the package is a time zone-aware pd.Timestamp in New
York time, every calendar day is a datetime.date, and every duration is a
pd.Timedelta. Values of other types are converted only where they are passed
to or received from another package.

Truncate a timestamp with replace(second=0, microsecond=0, nanosecond=0)
rather than floor(), which fails in the hour that repeats when daylight saving
time ends. Adding pd.Timedelta(days=1) to a timestamp adds 24 hours, so the
midnight that starts the next day is pd.Timestamp(day + pd.Timedelta(days=1),
tz=NY).

Attributes
----------
NY: ZoneInfo
    The New York time zone, which every timestamp in the package carries.

Functions
---------
now
    Return the current time.
today
    Return the current date in New York.
market_open
    Return the time the regular US equities session opens on a day.
"""

from datetime import date, time
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")


def now() -> pd.Timestamp:
    """Return the current time, in New York time."""
    return pd.Timestamp.now(tz=NY)


def today() -> date:
    """Return the current date in New York."""
    return now().date()


def market_open(day: date) -> pd.Timestamp:
    """Return the time the regular US equities session opens on a day.

    Parameters
    ----------
    day: date
        The day.

    Returns
    -------
    Return 9:30 New York time on day.
    """
    return pd.Timestamp.combine(day, time(9, 30)).tz_localize(NY)
