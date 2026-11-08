"""Alpaca streaming provider.

Classes
-------
AlpacaStream
    Streaming provider for the Alpaca WebSocket API.
"""

import asyncio
import logging
import queue
from random import randint
from typing import Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from alpaca.common.enums import BaseURL
from alpaca.data.enums import DataFeed
from alpaca.data.live import CryptoDataStream, StockDataStream
from alpaca.data.live.websocket import DataStream

from liualgotrader.common import clock
from liualgotrader.common.list_utils import list_chunks
from liualgotrader.common.types import (QueueMessageType, SymbolQueueMap,
                                        WSEventType)
from liualgotrader.stream.base import StreamingAPI
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.alpaca.util import (alpaca_time, crypto_pair,
                                               is_crypto_symbol)

logger = logging.getLogger(__name__)

_STREAM_FEEDS = (DataFeed.IEX, DataFeed.SIP)


def _whole(value: float) -> Union[int, float]:
    """Return a number as an int if it has no fractional part.

    Parameters
    ----------
    value: float
        The number to convert.
    """
    return int(value) if float(value).is_integer() else value


class AlpacaStream(StreamingAPI):
    """Streaming provider for the Alpaca WebSocket API.

    Supports US equities and the Bitcoin and Ethereum US dollar pairs.

    Attributes
    ----------
    config: AlpacaConfig
        The connection settings.
    stock_ws_client: StockDataStream
        The Alpaca WebSocket client for equities.
    crypto_ws_client: CryptoDataStream
        The Alpaca WebSocket client for crypto pairs.
    crypto_symbols: Dict[str, str]
        The subscribed crypto symbols, keyed by Alpaca crypto pair.
    task: Optional[asyncio.Task]
        The background streaming task, or None before run.

    Methods
    -------
    run
        Start the WebSocket clients in the background.
    subscribe
        Subscribe to event types for the given symbols.
    close
        Stop the WebSocket clients.
    """

    def __init__(self, queues: SymbolQueueMap, config: AlpacaConfig):
        """Initialize the WebSocket clients and register the shared instance.

        Parameters
        ----------
        queues: QueueMapper
            The mapper from each symbol to its event queue.
        config: AlpacaConfig
            The connection settings.

        Raises
        ------
        Raise ValueError if config.data_feed is not an Alpaca data feed, and
        AssertionError if a client cannot be created.
        """
        self.config = config
        feed = DataFeed(config.data_feed.lower())
        self.stock_ws_client = StockDataStream(
            api_key=config.api_key,
            secret_key=config.api_secret,
            feed=feed if feed in _STREAM_FEEDS else DataFeed.SIP,
            # the client only accepts the IEX and SIP feeds by name
            url_override=(
                None
                if feed in _STREAM_FEEDS
                else f"{BaseURL.MARKET_DATA_STREAM.value}/v2/{feed.value}"
            ),
        )
        self.crypto_ws_client = CryptoDataStream(
            api_key=config.api_key,
            secret_key=config.api_secret,
        )

        if not (self.stock_ws_client and self.crypto_ws_client):
            raise AssertionError(
                "Failed to authenticate Alpaca web_socket client"
            )

        self.crypto_symbols: Dict[str, str] = {}
        self.task: Optional[asyncio.Task] = None
        self._client_tasks: Dict[DataStream, asyncio.Task] = {}
        self._stop_event = asyncio.Event()
        super().__init__(queues)

    async def run(self):
        """Start streaming in the background, if not yet running.

        Each WebSocket client connects once it has a subscription.

        Raises
        ------
        Raise AssertionError if no queues are set.
        """
        if not self.task:
            if self.queues:
                self.task = asyncio.create_task(self._run_clients())
            else:
                raise AssertionError(
                    "can't call `AlpacaStream.run()` without queues"
                )

    async def _run_clients(self) -> None:
        """Run the subscribed WebSocket clients until close is called."""
        for client in (self.stock_ws_client, self.crypto_ws_client):
            if any(client._handlers.values()):
                self._start_client(client)

        await self._stop_event.wait()
        await asyncio.gather(*self._client_tasks.values())

    def _start_client(self, client: DataStream) -> None:
        """Run a WebSocket client in the background.

        Do nothing before run or if the client was already started.

        Parameters
        ----------
        client: DataStream
            The client to run.
        """
        # client.run() calls asyncio.run(), which cannot run inside this
        # event loop. Start a client only once it has a subscription, since
        # until then it busy-waits for one.
        if self.task and client not in self._client_tasks:
            self._client_tasks[client] = asyncio.create_task(
                client._run_forever()
            )

    @staticmethod
    def _add_subscription(
        client: DataStream,
        subscribe: Callable[..., None],
        handler: Callable,
        symbols: List[str],
    ) -> None:
        """Register a handler for symbols on a WebSocket client.

        Do not send the subscription; see _send_subscriptions.

        Parameters
        ----------
        client: DataStream
            The client to register with.
        subscribe: Callable[..., None]
            The client's subscription method for the event type.
        handler: Callable
            The coroutine function to handle the events.
        symbols: List[str]
            The symbols to subscribe to, in the client's format.
        """
        if not symbols:
            return

        # a running client would otherwise block the event loop until its
        # own coroutine, on this loop, sends the subscription
        running = client._running
        client._running = False
        try:
            subscribe(handler, *symbols)
        finally:
            client._running = running

    async def _send_subscriptions(self, client: DataStream) -> None:
        """Send the subscriptions of a connected client, or start it.

        A client that is not yet connected sends its subscriptions once it
        connects.

        Parameters
        ----------
        client: DataStream
            The client whose subscriptions changed.
        """
        if not client._running:
            self._start_client(client)
            return

        try:
            await client._send_subscribe_msg()
        except Exception as e:
            # the client subscribes again when it reconnects
            logger.error("subscribe(): %s %s", type(e).__name__, e)

    @classmethod
    async def _bar_handler(cls, msg):
        """Convert an equity bar into a MINUTE_BAR event and enqueue it.

        In the event, average holds the volume-weighted price and vwap is NaN.
        Propagate an exception if the queue is full; log and suppress any other
        error.

        Parameters
        ----------
        msg
            The Alpaca bar.
        """
        try:
            event = {
                "symbol": msg.symbol,
                "open": msg.open,
                "close": msg.close,
                "high": msg.high,
                "low": msg.low,
                "timestamp": alpaca_time(msg.timestamp),
                "volume": _whole(msg.volume),
                "count": int(msg.trade_count),
                "vwap": np.nan,
                "average": msg.vwap,
                "totalvolume": None,
                "EV": QueueMessageType.MINUTE_BAR,
            }
            cls.get_instance().queues[msg.symbol].put(event, timeout=1)
        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                msg.symbol,
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

    @classmethod
    async def _crypto_bar_handler(cls, msg):
        """Convert a crypto bar into a MINUTE_BAR event and enqueue it.

        Name the pair as it was subscribed. Otherwise behave like
        _bar_handler.

        Parameters
        ----------
        msg
            The Alpaca crypto bar.
        """
        try:
            symbol = cls.get_instance().crypto_symbols.get(
                msg.symbol, msg.symbol
            )
            event = {
                "symbol": symbol,
                "open": msg.open,
                "close": msg.close,
                "high": msg.high,
                "low": msg.low,
                "timestamp": alpaca_time(msg.timestamp),
                "volume": msg.volume,
                "count": int(msg.trade_count),
                "vwap": np.nan,
                "average": msg.vwap,
                "totalvolume": None,
                "EV": QueueMessageType.MINUTE_BAR,
            }
            cls.get_instance().queues[symbol].put(event, timeout=1)
        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                msg.symbol,
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

    @classmethod
    async def _trades_handler(cls, msg):
        """Convert an equity trade into a TRADE event and enqueue it.

        Occasionally log a warning for trades more than ten seconds old.
        Propagate an exception if the queue is full; log and suppress any other
        error.

        Parameters
        ----------
        msg
            The Alpaca trade.
        """
        try:
            ts = alpaca_time(msg.timestamp)
            if (time_diff := (clock.now() - ts)) > pd.Timedelta(
                seconds=10
            ) and randint(  # nosec
                1, 100
            ) == 1:  # nosec
                logger.info(
                    "Received trade for %s too out of sync w %s",
                    msg.symbol,
                    time_diff,
                )

            event = {
                "symbol": msg.symbol,
                "price": msg.price,
                "open": msg.price,
                "close": msg.price,
                "high": msg.price,
                "low": msg.price,
                "timestamp": ts,
                "volume": _whole(msg.size),
                "exchange": msg.exchange,
                "conditions": (
                    msg.conditions if hasattr(msg, "conditions") else None
                ),
                "tape": msg.tape if hasattr(msg, "tape") else None,
                "average": np.nan,
                "count": 1,
                "vwap": np.nan,
                "EV": QueueMessageType.TRADE,
            }

            cls.get_instance().queues[msg.symbol].put(event, block=False)

        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                msg.symbol,
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

    @classmethod
    async def _crypto_trades_handler(cls, msg):
        """Convert a crypto trade into a TRADE event and enqueue it.

        Name the pair as it was subscribed. Otherwise behave like
        _trades_handler.

        Parameters
        ----------
        msg
            The Alpaca crypto trade.
        """
        try:
            symbol = cls.get_instance().crypto_symbols.get(
                msg.symbol, msg.symbol
            )
            ts = alpaca_time(msg.timestamp)
            if (time_diff := (clock.now() - ts)) > pd.Timedelta(
                seconds=10
            ) and randint(  # nosec
                1, 100
            ) == 1:  # nosec
                logger.info(
                    "Received trade for %s too out of sync w %s",
                    symbol,
                    time_diff,
                )

            event = {
                "symbol": symbol,
                "price": msg.price,
                "open": msg.price,
                "close": msg.price,
                "high": msg.price,
                "low": msg.price,
                "timestamp": ts,
                "volume": msg.size,
                "exchange": msg.exchange,
                "conditions": (
                    msg.conditions if hasattr(msg, "conditions") else None
                ),
                "tape": msg.tape if hasattr(msg, "tape") else None,
                "average": np.nan,
                "count": 1,
                "vwap": np.nan,
                "EV": QueueMessageType.TRADE,
            }

            cls.get_instance().queues[symbol].put(event, block=False)

        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is FULL:%s",
                msg.symbol,
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

    @classmethod
    async def _quotes_handler(cls, msg):
        """Discard a quote message.

        Parameters
        ----------
        msg
            The Alpaca quote.
        """
        pass

    async def subscribe(
        self, symbols: List[str], events: List[WSEventType]
    ) -> bool:
        """Subscribe to event types for the given symbols.

        Parameters
        ----------
        symbols: List[str]
            The equity symbols and crypto pairs to subscribe to.
        events: List[WSEventType]
            The event types to receive; types other than minute bars, trades
            and quotes are ignored.

        Returns
        -------
        Return True.
        """
        logger.info("Starting subscription for %s symbols", len(symbols))
        upper_symbols = [symbol.upper() for symbol in symbols]
        stock, crypto = self.stock_ws_client, self.crypto_ws_client
        for syms in list_chunks(upper_symbols, 1000):
            logger.info("\tsubscribe %s/%s", len(syms), len(upper_symbols))

            crypto_symbols = list(filter(is_crypto_symbol, syms))
            equity_symbols = [x for x in syms if x not in crypto_symbols]
            crypto_pairs = [crypto_pair(x) for x in crypto_symbols]
            self.crypto_symbols.update(zip(crypto_pairs, crypto_symbols))

            for event in events:
                if event == WSEventType.MIN_AGG:
                    self._add_subscription(
                        crypto,
                        crypto.subscribe_bars,
                        AlpacaStream._crypto_bar_handler,
                        crypto_pairs,
                    )
                    self._add_subscription(
                        stock,
                        stock.subscribe_bars,
                        AlpacaStream._bar_handler,
                        equity_symbols,
                    )
                elif event == WSEventType.TRADE:
                    self._add_subscription(
                        crypto,
                        crypto.subscribe_trades,
                        AlpacaStream._crypto_trades_handler,
                        crypto_pairs,
                    )
                    self._add_subscription(
                        stock,
                        stock.subscribe_trades,
                        AlpacaStream._trades_handler,
                        equity_symbols,
                    )
                elif event == WSEventType.QUOTE:
                    self._add_subscription(
                        crypto,
                        crypto.subscribe_quotes,
                        AlpacaStream._quotes_handler,
                        crypto_pairs,
                    )
                    self._add_subscription(
                        stock,
                        stock.subscribe_quotes,
                        AlpacaStream._quotes_handler,
                        equity_symbols,
                    )

            if crypto_pairs:
                await self._send_subscriptions(crypto)
            if equity_symbols:
                await self._send_subscriptions(stock)

            await asyncio.sleep(1)

        logger.info("Completed subscription for %s symbols", len(symbols))
        return True

    async def close(self) -> None:
        """Stop the WebSocket clients and wait for streaming to end."""
        logger.info("Closing AlpacaStream")

        if self.task:
            for client in self._client_tasks:
                await client.stop_ws()
            self._stop_event.set()

            while not self.task.done():
                await asyncio.sleep(1.0)

            logger.info("Task Done. Closed AlpacaStream")
