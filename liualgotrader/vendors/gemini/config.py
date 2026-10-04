"""Connection settings for the Gemini API.

Classes
-------
GeminiConfig
    Connection settings for the Gemini API.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GeminiConfig:
    """Connection settings for the Gemini API.

    Attributes
    ----------
    api_key: Optional[str]
        The API key.
    api_secret: Optional[str]
        The API secret.
    base_url: str
        The REST API base URL.
    base_websocket: str
        The websocket API base URL.
    trading_base_url: str
        The REST API base URL for trading.
    trading_base_websocket: str
        The websocket API base URL for trading.
    debug_enabled: bool
        Whether to log the traceback of errors in stream handlers.
    """

    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    base_url: str = "https://api.gemini.com"
    base_websocket: str = "wss://api.gemini.com"
    trading_base_url: str = "https://api.sandbox.gemini.com"
    trading_base_websocket: str = "wss://api.sandbox.gemini.com"
    debug_enabled: bool = False
