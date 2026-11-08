"""Connection settings for the Tradier API.

Classes
-------
TradierConfig
    Connection settings for the Tradier API.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TradierConfig:
    """Connection settings for the Tradier API.

    Attributes
    ----------
    base_url: str
        The REST API base URL, ending with a slash.
    websocket_base: str
        The streaming API base URL, ending with a slash.
    account_number: Optional[str]
        The brokerage account number.
    access_token: Optional[str]
        The API access token.
    request_attempts: int
        How many times to send a request that is rejected as rate-limited or
        unavailable, with status 429 or 502.
    request_retry_seconds: float
        The seconds to wait between tries.
    """

    base_url: str = "https://sandbox.tradier.com/v1/"
    websocket_base: str = "wss://ws.tradier.com/v1/"
    account_number: Optional[str] = None
    access_token: Optional[str] = None
    request_attempts: int = 6
    request_retry_seconds: float = 10.0
