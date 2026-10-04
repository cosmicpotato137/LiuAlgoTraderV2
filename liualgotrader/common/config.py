"""Framework-wide configuration settings.

Most settings are module-level variables, many read from environment
variables at import time, such as the data connector, broker, database DSN
and performance parameters. Shared run-time values, such as the batch ID, are
set later.

Functions
---------
installed_version
    Return the version of the installed liualgotrader distribution.
"""

import os
from importlib.metadata import PackageNotFoundError, version
from typing import List, Optional

from liualgotrader.common.types import BrokerType, DataConnectorType
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.finnhub.config import FinnhubConfig
from liualgotrader.vendors.gemini.config import GeminiConfig
from liualgotrader.vendors.polygon.config import PolygonConfig
from liualgotrader.vendors.tradier.config import TradierConfig


def installed_version() -> str:
    """Return the version of the installed liualgotrader distribution.

    Returns
    -------
    Return the installed version, or an empty string if liualgotrader is not
    installed.
    """
    try:
        return version("liualgotrader")
    except PackageNotFoundError:
        return ""


tradeplan_folder: str = (
    os.getenv("TRADEPLAN_DIR", ".")
    if len(os.getenv("TRADEPLAN_DIR", ".")) > 0
    else "."
)
configuration_filename: str = "tradeplan.toml"
miner_configuration_filename: str = "miner.toml"
env: str


data_connector: DataConnectorType = DataConnectorType[os.getenv("DATA_CONNECTOR", "alpaca")]  # type: ignore

# Performance, Debugging & Logging
trace_enabled = bool(int(os.getenv("LIU_TRACE_ENABLED", 0)))
debug_enabled = bool(int(os.getenv("LIU_DEBUG_ENABLED", 0)))
log_level: str = os.getenv("LIU_LOG_LEVEL", "INFO").upper()

#
# Broker
#
broker: BrokerType = BrokerType[os.getenv("LIU_BROKER", "alpaca")]

# total number of tickers to follow
total_tickers = 000

#
# Shared data
#
build_label: str = installed_version()
filename: str
batch_id: str

#
# Data providers and brokers
#
# Replace these with your API connection info from the dashboard
alpaca = AlpacaConfig(
    api_key=os.getenv("APCA_API_KEY_ID", AlpacaConfig.api_key),
    api_secret=os.getenv("APCA_API_SECRET_KEY", AlpacaConfig.api_secret),
    base_url=os.getenv("APCA_API_BASE_URL", AlpacaConfig.base_url),
    data_feed=os.getenv("ALPACA_DATA_FEED", AlpacaConfig.data_feed),
    stream_url=os.getenv("ALPACA_STREAM_URL", AlpacaConfig.stream_url),
    broker_api_base_url=os.getenv(
        "ALPACA_BROKER_API_BASEURL", AlpacaConfig.broker_api_base_url
    ),
    broker_api_key=os.getenv(
        "ALPACA_BROKER_API_KEY", AlpacaConfig.broker_api_key
    ),
    broker_api_secret=os.getenv(
        "ALPACA_BROKER_API_SECRET", AlpacaConfig.broker_api_secret
    ),
    debug_enabled=debug_enabled,
)

polygon = PolygonConfig(
    api_key=os.getenv("POLYGON_API_KEY", PolygonConfig.api_key),
)

gemini = GeminiConfig(
    api_key=os.getenv("GEMINI_API_KEY", GeminiConfig.api_key),
    api_secret=os.getenv("GEMINI_API_SECRET", GeminiConfig.api_secret),
    debug_enabled=debug_enabled,
)

tradier = TradierConfig(
    base_url=os.getenv("TRADIER_BASE_URL", TradierConfig.base_url),
    websocket_base=os.getenv("TRADIER_WS_URL", TradierConfig.websocket_base),
    account_number=os.getenv(
        "TRADIER_ACCOUNT_NUMBER", TradierConfig.account_number
    ),
    access_token=os.getenv("TRADIER_ACCESS_TOKEN", TradierConfig.access_token),
)

finnhub = FinnhubConfig(
    api_key=os.getenv("FINNHUB_API_KEY", FinnhubConfig.api_key),
    base_url=os.getenv("FINNHUB_BASE_URL", FinnhubConfig.base_url),
)

#
# Execution details (env variable)
dsn: str = os.getenv("DSN", "")


# Stop limit to default to
default_stop = 0.95

# How much of our portfolio to allocate to any one position
risk = 0.001
portfolio_value: Optional[float] = None

group_margin = 0.02

# trade times
market_liquidation_end_time_minutes: int = 15


#
# WS Data Channels
#
WS_DATA_CHANNELS: List[str]


# performance parameters
proc_factor: float = float(os.getenv("CPU_FACTOR", "2.0"))
num_consumers: int = int(os.getenv("NUM_CONSUMERS", "0"))

num_consumer_processes_ratio: int
