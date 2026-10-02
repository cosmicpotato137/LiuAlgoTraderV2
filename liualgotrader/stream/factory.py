"""Create the configured streaming provider.

Functions
---------
streaming_factory
    Return a new streaming provider for a connector.
"""

from liualgotrader.common import config
from liualgotrader.common.types import DataConnectorType, SymbolQueueMap
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.vendors.alpaca.streaming import AlpacaStream
from liualgotrader.vendors.gemini.streaming import GeminiStream
from liualgotrader.vendors.polygon.streaming import PolygonStream


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
