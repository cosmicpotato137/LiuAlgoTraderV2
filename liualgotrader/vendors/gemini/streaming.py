"""Gemini cryptocurrency exchange streaming provider.

Classes
-------
GeminiStream
    Streaming provider for Gemini trades.
"""

import base64
import hashlib
import hmac
import json
import logging
import queue
import ssl
import time
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Dict, List, Optional

import pandas as pd
import pytz
import websocket

from liualgotrader.common.types import SymbolQueueMap, WSEventType
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.vendors.gemini.config import GeminiConfig

logger = logging.getLogger(__name__)

utctz = pytz.timezone("UTC")


class GeminiStream(StreamingAPI):
    """StreamingAPI implementation for Gemini trades.

    Only btcusd trades are streamed, whatever the subscriptions.

    Attributes
    ----------
    config: GeminiConfig
        The connection settings.
    running_task: Optional[Thread]
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
        Return True without subscribing.
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
        self.running_task: Optional[Thread] = None
        self.ws = None
        super().__init__(queues)

    def _generate_ws_headers(self, payload: Dict) -> Dict:
        """Return the Gemini authentication headers for a websocket request.

        Parameters
        ----------
        payload: Dict
            The request payload; a nonce is added to it in place.

        Raises
        ------
        Raise AssertionError if the API key or secret is not set.
        """
        if not self.config.api_secret or not self.config.api_key:
            raise AssertionError(
                "both env variables GEMINI_API_KEY and GEMINI_API_SECRET must be set up"
            )
        t = datetime.now()
        payload_nonce = str(int(time.mktime(t.timetuple()) * 1000))
        payload["nonce"] = payload_nonce
        encoded_payload = json.dumps(payload).encode()
        b64 = base64.b64encode(encoded_payload)
        signature = hmac.new(
            self.config.api_secret.encode(), b64, hashlib.sha384
        ).hexdigest()

        return {
            "X-GEMINI-APIKEY": self.config.api_key,
            "X-GEMINI-PAYLOAD": b64.decode(),
            "X-GEMINI-SIGNATURE": signature,
        }

    async def run(self):
        """Start the btcusd websocket on a background thread, if not started.

        Connect without TLS certificate verification.

        Returns
        -------
        Return the thread.

        Raises
        ------
        Raise AssertionError if the API key or secret is not set.
        """
        if not self.running_task:
            endpoint = "/v1/marketdata/btcusd"  # TODO need support all symbols in an efficient way
            payload = {"request": endpoint}
            headers = self._generate_ws_headers(payload)
            self.ws = websocket.WebSocketApp(
                f"{self.config.base_websocket}{endpoint}?trades=true&heartbeat=true",
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                header=headers,
            )
            self.running_task = Thread(
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

    @classmethod
    def _on_message(cls, ws, msgs):
        """Pass each trade event in a websocket message to _trades_handler.

        Ignore messages that are not updates.

        Parameters
        ----------
        ws
            The websocket; unused.
        msgs
            The JSON message text.
        """
        msg = json.loads(msgs)

        if msg["type"] != "update":
            return

        for event in msg["events"]:
            if event["type"] == "trade":
                cls._trades_handler(
                    pd.Timestamp(
                        datetime.fromtimestamp(msg["timestamp"]).astimezone(
                            utctz
                        )
                    ),
                    event,
                )

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
    def _trades_handler(cls, timestamp: datetime, event: Dict):
        """Put a Gemini trade on the btcusd queue as a normalized trade event.

        Log trades received more than two seconds late.

        Parameters
        ----------
        timestamp: datetime
            The time of the trade, timezone-aware.
        event: Dict
            The Gemini trade event.

        Raises
        ------
        Raise an exception if the queue is full; log and suppress any other
        error.
        """
        try:
            if (time_diff := (datetime.now(timezone.utc) - timestamp)) > timedelta(seconds=2):  # type: ignore
                # if randint(1, 100) == 1:  # nosec
                logger.info(
                    "received a trade for btcusd out of sync w %s", time_diff
                )

            event = {
                "symbol": "btcusd",
                "price": float(event["price"]),
                "open": float(event["price"]),
                "close": float(event["price"]),
                "high": float(event["price"]),
                "low": float(event["price"]),
                "timestamp": timestamp,
                "volume": float(event["amount"]),
                "exchange": "gemini",
                "conditions": event["makerSide"],
                "tape": "",
                "average": None,
                "count": 1,
                "vwap": None,
                "EV": "T",
            }

            cls.get_instance().queues["btcusd"].put(event, block=False)

        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                event["sym"],
                f,
            )
            raise
        except AssertionError as e:
            logger.error("GEMINI process_message(): %s", e)
            time.sleep(1)
            return
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
        """Return True without subscribing, as the stream is fixed to btcusd.

        Parameters
        ----------
        symbols: List[str]
            Ignored.
        events: List[WSEventType]
            Ignored.
        """
        return True  # TODO Gemini - handle all symbols and event types
