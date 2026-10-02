"""Create the configured market data and streaming providers.

Functions
---------
data_loader_factory
    Return a new historical data provider for a connector.
streaming_factory
    Return a new streaming provider for a connector.
"""

from liualgotrader.common import config
from liualgotrader.common.types import DataConnectorType, SymbolQueueMap
from liualgotrader.data.alpaca import AlpacaData, AlpacaStream
from liualgotrader.data.data_base import DataAPI
from liualgotrader.data.finnhub import FinnhubData
from liualgotrader.data.gemini import GeminiData, GeminiStream
from liualgotrader.data.polygon import PolygonData, PolygonStream
from liualgotrader.data.streaming_base import StreamingAPI
from liualgotrader.data.tradier import TradierData


def data_loader_factory(connector: DataConnectorType = None) -> DataAPI:
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


def streaming_factory(
    queues: SymbolQueueMap, connector: DataConnectorType = None
) -> StreamingAPI:
    """Return a new streaming provider for a connector.

    The provider is created with the connector's settings from config, and
    becomes the shared instance that StreamingAPI.get_instance returns.

    Parameters
    ----------
    queues: QueueMapper
        The mapper from each symbol to its event queue.
    connector: DataConnectorType, default None
        The data connector, or None for the configured connector.

    Raises
    ------
    Raise Exception if the connector does not support streaming.
    """
    _connector = connector or config.data_connector
    if _connector == DataConnectorType.polygon:
        return PolygonStream(queues, config.polygon)
    elif _connector == DataConnectorType.alpaca:
        return AlpacaStream(queues, config.alpaca)
    elif _connector == DataConnectorType.gemini:
        return GeminiStream(queues, config.gemini)
    else:
        raise Exception(f"unsupported streaming provider {_connector}")
