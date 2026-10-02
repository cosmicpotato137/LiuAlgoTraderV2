"""Connection settings for the Alpaca APIs.

Classes
-------
AlpacaConfig
    Connection settings for the Alpaca APIs.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AlpacaConfig:
    """Connection settings for the Alpaca APIs.

    Attributes
    ----------
    api_key: str
        The API key ID.
    api_secret: str
        The API secret key.
    base_url: Optional[str]
        The trading API base URL, or None for the live trading URL.
    crypto_base_url: str
        The crypto market data API base URL.
    data_feed: str
        The name of the equity data feed to stream.
    stream_url: Optional[str]
        The streaming API URL.
    broker_api_base_url: Optional[str]
        The Broker API base URL, for orders of external accounts.
    broker_api_key: Optional[str]
        The Broker API key.
    broker_api_secret: Optional[str]
        The Broker API secret.
    debug_enabled: bool
        Whether to print the traceback of errors in event handlers.
    detailed_dl_debug_enabled: bool
        Whether to log each historical data request.
    """

    api_key: str = ""
    api_secret: str = ""
    base_url: Optional[str] = None
    crypto_base_url: str = "https://data.alpaca.markets/v1beta2/crypto"
    data_feed: str = "sip"
    stream_url: Optional[str] = None
    broker_api_base_url: Optional[str] = None
    broker_api_key: Optional[str] = None
    broker_api_secret: Optional[str] = None
    debug_enabled: bool = False
    detailed_dl_debug_enabled: bool = False
