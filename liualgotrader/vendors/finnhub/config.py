"""Connection settings for the Finnhub API.

Classes
-------
FinnhubConfig
    Connection settings for the Finnhub API.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FinnhubConfig:
    """Connection settings for the Finnhub API.

    Attributes
    ----------
    api_key: Optional[str]
        The API key.
    base_url: Optional[str]
        The API base URL.
    websocket_limit: int
        The maximum number of symbols to stream.
    """

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    websocket_limit: int = 50
