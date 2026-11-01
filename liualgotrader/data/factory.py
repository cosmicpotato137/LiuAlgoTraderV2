"""Create the configured market data provider.

Functions
---------
data_api_factory
    Return a new historical data provider for a connector.
"""

from liualgotrader.common import config
from liualgotrader.common.types import DataConnectorType
from liualgotrader.data.base import DataAPI
from liualgotrader.vendors.alpaca.data import AlpacaData
from liualgotrader.vendors.finnhub.data import FinnhubData
from liualgotrader.vendors.gemini.data import GeminiData
from liualgotrader.vendors.polygon.data import PolygonData
from liualgotrader.vendors.tradier.data import TradierData


def data_api_factory(connector: DataConnectorType = None) -> DataAPI:
    """Return a new historical data provider for a connector.

    The provider is created with the connector's settings from config.

    Parameters
    ----------
    connector: DataConnectorType, default None
        The data connector, or None for the configured connector.

    Raises
    ------
    Raise Exception if the connector is not supported.
    """
    _connector = connector or config.data_connector
    if _connector == DataConnectorType.polygon:
        return PolygonData(config.polygon)
    elif _connector == DataConnectorType.alpaca:
        return AlpacaData(config.alpaca)
    elif _connector == DataConnectorType.finnhub:
        return FinnhubData(config.finnhub)
    elif _connector == DataConnectorType.gemini:
        return GeminiData(config.gemini)
    elif _connector == DataConnectorType.tradier:
        return TradierData(config.tradier)
    else:
        raise Exception(f"unsupported data provider {_connector}")
