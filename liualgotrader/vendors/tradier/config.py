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
    """

    base_url: str = "https://sandbox.tradier.com/v1/"
    websocket_base: str = "wss://ws.tradier.com/v1/"
    account_number: Optional[str] = None
    access_token: Optional[str] = None
