"""Gemini cryptocurrency exchange streaming provider.

Classes
-------
GeminiStream
    Streaming provider for Gemini trades and minute bars.
"""

import asyncio
import json
import logging
import queue
import ssl
import threading
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import websocket

from liualgotrader.common import clock
from liualgotrader.common.types import SymbolQueueMap, WSEventType
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.vendors.gemini.config import GeminiConfig

logger = logging.getLogger(__name__)

# The market data subscription that delivers each supported event type. The
# l2 subscription also delivers order book changes, which are discarded.
_SUBSCRIPTIONS = {
    WSEventType.TRADE: "l2",
    WSEventType.MIN_AGG: "candles_1m",
}


def _gemini_time(milliseconds: int) -> pd.Timestamp:
    """Return a Gemini time in milliseconds as a timestamp in New York time.

    Parameters
    ----------
    milliseconds: int
        The Unix time in milliseconds.
    """
    return pd.Timestamp(milliseconds, unit="ms", tz="UTC").tz_convert(clock.NY)


class GeminiStream(StreamingAPI):
    """StreamingAPI implementation for Gemini market data.

    A single connection to the version 2 market data API streams the trades
    and minute bars of every subscribed symbol. Quotes and second bars are not
    streamed.

    Attributes
    ----------
    config: GeminiConfig
        The connection settings.
    running_task: Optional[threading.Thread]
        The websocket thread, or None.
    ws
        The websocket connection, or None.

    Methods
    -------
    run
        Start the websocket on a background thread.
    close
        Stop the websocket thread.
    subscribe
        Subscribe to the trades or minute bars of symbols.
    """

    def __init__(self, queues: SymbolQueueMap, config: GeminiConfig):
        """Initialize the stream and register it as the shared instance.

        Parameters
        ----------
        queues: QueueMapper
            The mapping from each symbol to the queue for its events.
        config: GeminiConfig
            The connection settings.
        """
        self.config = config
        self.running_task: Optional[threading.Thread] = None
        self.ws = None
        self._connected = threading.Event()
        super().__init__(queues)

    async def run(self):
        """Start the market data websocket on a background thread.

        Do nothing if it is already started. Connect without TLS certificate
        verification.

        Returns
        -------
        Return the thread.
        """
        if not self.running_task:
            self._connected.clear()
            self.ws = websocket.WebSocketApp(
                f"{self.config.base_websocket}/v2/marketdata",
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self.running_task = threading.Thread(
                target=self.ws.run_forever,
                args=(None, {"cert_reqs": ssl.CERT_NONE}),
            )
            self.running_task.start()

        return self.running_task

    async def close(self):
        """Stop the websocket thread, if running, and wait for it to exit."""
        if self.running_task and self.running_task.is_alive():
            logger.info("close task %s", self.running_task)
            self.ws.keep_running = False
            self.running_task.join()
            logger.info("task terminated")
            self.ws = None
            self.running_task = None

    def _on_open(self, ws):
        """Record that the websocket is connected.

        Parameters
        ----------
        ws
            The websocket; unused.
        """
        self._connected.set()

    @classmethod
    def _on_message(cls, ws, message):
        """Enqueue the trade or minute bar in a websocket message.

        Gemini sends the closed minute bars of the last day when a candle
        subscription starts, newest first, and then each bar as its minute
        closes, so only the newest bar of each candle message is enqueued.
        Ignore order book changes, including the recent trades listed with
        them, and heartbeats.

        Parameters
        ----------
        ws
            The websocket; unused.
        message
            The JSON message text.
        """
        msg = json.loads(message)
        if msg["type"] == "trade":
            cls._trade_handler(msg)
        elif msg["type"] == "candles_1m_updates" and msg["changes"]:
            cls._bar_handler(msg["symbol"], msg["changes"][0])

    @classmethod
    def _on_error(cls, ws, error):
        """Log an error reported by the websocket.

        Parameters
        ----------
        ws
            The websocket; unused.
        error
            The reported error.
        """
        logger.error("GeminiStream %s", error)

    @classmethod
    def _on_close(cls, ws, close_status_code, close_msg):
        """Log the status code and message sent when the websocket closes.

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
            "on_close(): GeminiStream status=%s, close_msg=%s",
            close_status_code,
            close_msg,
        )

    @classmethod
    def _trade_handler(cls, msg: Dict):
        """Put a Gemini trade on the queue of its symbol as a trade event.

        Log trades received more than two seconds late.

        Parameters
        ----------
        msg: Dict
            The Gemini trade message.
        """
        timestamp = _gemini_time(msg["timestamp"])
        if (time_diff := clock.now() - timestamp) > pd.Timedelta(seconds=2):
            logger.info(
                "received a trade for %s out of sync w %s",
                msg["symbol"],
                time_diff,
            )

        price = float(msg["price"])
        cls._enqueue(
            {
                "symbol": msg["symbol"].lower(),
                "price": price,
                "open": price,
                "close": price,
                "high": price,
                "low": price,
                "timestamp": timestamp,
                "volume": float(msg["quantity"]),
                "exchange": "gemini",
                "conditions": msg["side"],
                "tape": "",
                "average": np.nan,
                "count": 1,
                "vwap": np.nan,
                "EV": "T",
            }
        )

    @classmethod
    def _bar_handler(cls, symbol: str, candle: List):
        """Put a Gemini minute bar on the queue of its symbol as an "AM" event.

        Parameters
        ----------
        symbol: str
            The symbol of the bar.
        candle: List
            The bar: its start time in milliseconds, then its open, high, low
            and close prices and its volume.
        """
        start, open_, high, low, close, volume = candle
        cls._enqueue(
            {
                "symbol": symbol.lower(),
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "timestamp": _gemini_time(start),
                "volume": volume,
                "count": 0,
                "vwap": np.nan,
                "average": np.nan,
                "totalvolume": None,
                "EV": "AM",
            }
        )

    @classmethod
    def _enqueue(cls, event: Dict):
        """Put an event on the queue of its symbol without blocking.

        Parameters
        ----------
        event: Dict
            The event.

        Raises
        ------
        Raise queue.Full if the queue is full; log and suppress any other
        error.
        """
        try:
            cls.get_instance().queues[event["symbol"]].put(event, block=False)
        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                event["symbol"],
                f,
            )
            raise
        except Exception as e:
            logger.error(
                "process_message(): exception of type %s with args %s",
                type(e).__name__,
                e.args,
                exc_info=cls.get_instance().config.debug_enabled,
            )

    async def subscribe(
        self, symbols: List[str], events: List[WSEventType]
    ) -> bool:
        """Subscribe to event types for the given symbols.

        Wait up to ten seconds for run to connect.

        Parameters
        ----------
        symbols: List[str]
            The symbols to subscribe to, in any letter case.
        events: List[WSEventType]
            The event types to receive; types other than trades and minute
            bars are ignored.

        Returns
        -------
        Return False if the websocket is not connected, and True otherwise.
        """
        if not self.ws or not await asyncio.to_thread(
            self._connected.wait, 10
        ):
            logger.error("GeminiStream.subscribe(): not connected")
            return False

        names = sorted(
            {_SUBSCRIPTIONS[e] for e in events if e in _SUBSCRIPTIONS}
        )
        if symbols and names:
            upper_symbols = [symbol.upper() for symbol in symbols]
            self.ws.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "subscriptions": [
                            {"name": name, "symbols": upper_symbols}
                            for name in names
                        ],
                    }
                )
            )
            logger.info(
                "GeminiStream subscribed %s to %s", upper_symbols, names
            )
        return True
