"""Connection settings for the Polygon APIs.

Classes
-------
PolygonConfig
    Connection settings for the Polygon APIs.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PolygonConfig:
    """Connection settings for the Polygon APIs.

    Attributes
    ----------
    api_key: Optional[str]
        The API key.
    seconds_timeout: int
        The request timeout, in seconds.
    max_days_to_load: int
        The maximum number of days of data to load.
    """

    api_key: Optional[str] = None
    seconds_timeout: int = 60
    max_days_to_load: int = 7
