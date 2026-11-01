"""Polygon streaming provider.

Classes
-------
PolygonStream
    Streaming provider for the Polygon WebSocket API.
"""

import asyncio
import json
import logging
import queue
from typing import Dict, List, Optional, Union

import pandas as pd
from polygon import WebSocketClient
from polygon.exceptions import AuthError
from polygon.websocket.models import EventType as PolygonEventType
from polygon.websocket.models import Feed, Market

from liualgotrader.common import clock
from liualgotrader.common.types import (QueueMessageType, SymbolQueueMap,
                                        WSEventType)
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.vendors.polygon.config import PolygonConfig

logger = logging.getLogger(__name__)

# Polygon websocket channel of each event type
_WS_CHANNELS: Dict[WSEventType, PolygonEventType] = {
    WSEventType.SEC_AGG: PolygonEventType.EquityAgg,
    WSEventType.MIN_AGG: PolygonEventType.EquityAggMin,
    WSEventType.TRADE: PolygonEventType.EquityTrade,
    WSEventType.QUOTE: PolygonEventType.EquityQuote,
}

# The queue message type of each Polygon event type that is forwarded
_QUEUE_MESSAGE_TYPES: Dict[PolygonEventType, QueueMessageType] = {
    PolygonEventType.EquityAgg: QueueMessageType.SECOND_BAR,
    PolygonEventType.EquityAggMin: QueueMessageType.MINUTE_BAR,
    PolygonEventType.EquityTrade: QueueMessageType.TRADE,
    PolygonEventType.EquityQuote: QueueMessageType.QUOTE,
}

# The raw ev codes of the forwarded Polygon event types
_FORWARDED_EVENT_CODES = {t.value for t in _QUEUE_MESSAGE_TYPES}

# seconds to wait for the stream task to end after closing the websocket
_CLOSE_TIMEOUT = 5.0


class PolygonStream(StreamingAPI):
    """StreamingAPI implementation backed by the Polygon websocket.

    Aggregate, trade and quote events are relayed to the per-symbol queues with
    descriptive field names added. The connection starts when run is called,
    and subscriptions made before then take effect once it is established.

    Attributes
    ----------
    config: PolygonConfig
        The connection settings.
    polygon_ws_client
        The Polygon websocket client.
    task: Optional[asyncio.Task]
        The background streaming task, or None before run.

    Methods
    -------
    subscribe
        Subscribe symbols to event types.
    run
        Start streaming in the background.
    unsubscribe
        Unsubscribe a symbol from every event type.
    close
        Close the websocket connection.
    """

    def __init__(self, queues: SymbolQueueMap, config: PolygonConfig):
        """Create the websocket client and register the shared instance.

        Parameters
        ----------
        queues: QueueMapper
            The mapping from each symbol to the queue for its events.
        config: PolygonConfig
            The connection settings.

        Raises
        ------
        Raise AssertionError if the client cannot be created, such as when
        config.api_key is not set.
        """
        self.config = config
        try:
            self.polygon_ws_client = WebSocketClient(
                api_key=config.api_key,
                feed=Feed.RealTime,
                market=Market.Stocks,
                raw=True,
            )
        except AuthError as e:
            raise AssertionError(
                "Failed to authenticate Polygon web_socket client"
            ) from e
        self.task: Optional[asyncio.Task] = None
        super().__init__(queues)

    async def subscribe(
        self, symbols: List[str], events: List[WSEventType]
    ) -> bool:
        """Subscribe each symbol to each of the given event types.

        Parameters
        ----------
        symbols: List[str]
            The symbols to subscribe, in any case.
        events: List[WSEventType]
            The aggregate, trade and quote event types.

        Returns
        -------
        Return True.
        """
        args = [
            f"{_WS_CHANNELS[event].value}.{symbol.upper()}"
            for symbol in symbols
            for event in events
        ]

        logger.info("subscribe(): adding subscription %s", args)
        self.polygon_ws_client.subscribe(*args)

        return True

    async def run(self):
        """Start streaming in the background unless a stream is running."""
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(
                self._stream(), name="PolygonStream"
            )

    async def unsubscribe(self, symbol: str) -> bool:
        """Unsubscribe a symbol from every event type.

        Parameters
        ----------
        symbol: str
            The symbol to unsubscribe, in any case.

        Returns
        -------
        Return True.
        """
        args = [
            f"{channel.value}.{symbol.upper()}"
            for channel in _WS_CHANNELS.values()
        ]

        logger.info("unsubscribe(): removing subscription %s", args)
        self.polygon_ws_client.unsubscribe(*args)

        return True

    async def close(
        self,
    ) -> None:
        """Close the Polygon websocket connection and stop streaming."""
        if self.polygon_ws_client.websocket:
            await self.polygon_ws_client.close()
            if self.task:
                await asyncio.wait({self.task}, timeout=_CLOSE_TIMEOUT)

        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _stream(self) -> None:
        """Relay Polygon messages to the queues until the connection ends.

        Report errors to _on_error and the end of the connection to _on_close
        instead of raising them.
        """
        try:
            await self.polygon_ws_client.connect(PolygonStream._on_message)
        except Exception as e:
            PolygonStream._on_error(self.polygon_ws_client.websocket, e)
        finally:
            ws = self.polygon_ws_client.websocket
            PolygonStream._on_close(
                ws,
                getattr(ws, "close_code", None),
                getattr(ws, "close_reason", None),
            )

    @classmethod
    async def _on_message(cls, message: Union[str, bytes]) -> None:
        """Handle one message, reporting any error to _on_error.

        The message is handled in a worker thread, so a full queue does not
        block the event loop.

        Parameters
        ----------
        message: Union[str, bytes]
            The JSON text of a list of events.
        """
        try:
            await asyncio.to_thread(cls._process_message, message)
        except Exception as e:
            cls._on_error(None, e)

    @classmethod
    def _handle_event(cls, event: Dict):
        """Put a Polygon event on the queue for its symbol.

        Log the event at debug level.

        Parameters
        ----------
        event: Dict
            The Polygon event; descriptive field names such as open and symbol
            are added to it in place, and timestamp holds the start time of
            an aggregate, or the time of a trade or quote.

        Raises
        ------
        Raise queue.Full if the queue stays full for one second; log and
        suppress any other error.
        """
        logger.debug("event: %s", event)
        try:
            polygon_type = PolygonEventType(event["ev"])
            event["EV"] = _QUEUE_MESSAGE_TYPES[polygon_type]
            # aggregates start at s, while trades and quotes happen at t;
            # both are Unix milliseconds, and a trade's s is its size
            is_aggregate = polygon_type in (
                PolygonEventType.EquityAgg,
                PolygonEventType.EquityAggMin,
            )
            event["timestamp"] = pd.Timestamp(
                event["s"] if is_aggregate else event["t"],
                unit="ms",
                tz="UTC",
            ).tz_convert(clock.NY)
            if "o" in event:
                event["open"] = event["o"]
            if "h" in event:
                event["high"] = event["h"]
            if "l" in event:
                event["low"] = event["l"]
            if "c" in event:
                event["close"] = event["c"]
            if "v" in event:
                event["volume"] = event["v"]
            if "vw" in event:
                event["vwap"] = event["vw"]
            if "a" in event:
                event["average"] = event["a"]
            if "av" in event:
                event["totalvolume"] = event["av"]
            if "sym" in event:
                event["symbol"] = event["sym"]
            if "z" in event:
                event["count"] = event["z"]
            cls.get_instance().queues[event["sym"]].put(event, timeout=1)
        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s, sleeping for 2 seconds and re-trying.",
                event["sym"],
                f,
            )
            raise
        except Exception as e:
            logger.exception(
                "process_message(): exception of type %s with args %s",
                type(e).__name__,
                e.args,
            )

    @classmethod
    def _process_message(cls, message):
        """Handle each aggregate, trade and quote event in a message.

        Ignore events of other types.

        Parameters
        ----------
        message
            The JSON text of a list of events, as str or bytes.
        """
        payload = json.loads(message)
        for event in payload:
            if event["ev"] in _FORWARDED_EVENT_CODES:
                cls._handle_event(event)

    @classmethod
    def _on_error(cls, ws, error):
        """Log an error reported by the websocket client.

        Parameters
        ----------
        ws
            The websocket; unused.
        error
            The reported error.
        """
        logger.error("on_error(): %s", error)

    @classmethod
    def _on_close(cls, ws, close_status_code, close_msg):
        """Log the status code and message sent when the connection closes.

        Parameters
        ----------
        ws
            The websocket; unused.
        close_status_code
            The close status code.
        close_msg
            The close message.
        """
        logger.info(
            "on_close() called with (%s, %s)", close_status_code, close_msg
        )
