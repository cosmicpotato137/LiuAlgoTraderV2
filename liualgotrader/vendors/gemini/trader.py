"""Gemini cryptocurrency exchange trader.

Classes
-------
GeminiOrderType
    Enumeration of the Gemini order types that this trader submits.
GeminiTrader
    Trader implementation for the Gemini cryptocurrency exchange.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import queue
import ssl
import time
from datetime import date
from enum import StrEnum
from threading import Thread
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import websocket

from liualgotrader.common import clock
from liualgotrader.common.assets import get_asset_min_qty, round_asset
from liualgotrader.common.types import (Order, OrderType, QueueMessageType,
                                        SymbolQueueMap, ThreadFlags, Trade)
from liualgotrader.trade.base import TraderAPI
from liualgotrader.vendors.gemini.config import GeminiConfig

logger = logging.getLogger(__name__)


class GeminiOrderType(StrEnum):
    """Enumeration of the Gemini order types that this trader submits."""

    EXCHANGE_LIMIT = "exchange limit"


class GeminiTrader(TraderAPI):
    """Trader implementation for the Gemini cryptocurrency exchange.

    The market is treated as open all day, every New York calendar day; all
    symbols are fractionable, none is shortable, and market orders are
    rejected. Requests go to the trading URLs of the config, which are the
    Gemini sandbox by default.

    Attributes
    ----------
    config: GeminiConfig
        The connection settings.
    running_task: Optional[asyncio.Task]
        The order event listener, or None.
    hb_task: Optional[Thread]
        The heartbeat thread, or None.
    send_hb
        A heartbeat setting, always True.
    ws
        The order event WebSocket application, or None.
    flags: Optional[ThreadFlags]
        The flags that keep the heartbeat thread running, or None.
    last_nonce: Optional[int]
        The nonce of the latest signed REST request, or None.

    Methods
    -------
    is_fractionable
        Return True for every symbol (overrides Trader).
    _check_error
        Raise AssertionError if a Gemini response reports an error.
    is_order_completed
        Return the status, price, quantity and fees of an order (overrides
        Trader).
    get_market_schedule
        Return the whole of today as the session (overrides Trader).
    get_trading_days
        Return every calendar day in a range (overrides Trader).
    get_position
        Return the balance held in a currency (overrides Trader).
    get_order
        Return the current state of an order (overrides Trader).
    is_market_open_today
        Return True (overrides Trader).
    get_time_market_close
        Return the time left in the day (overrides Trader).
    reconnect
        Restart the listener and heartbeat thread (overrides Trader).
    _heartbeat
        Send heartbeats to Gemini until told to stop.
    on_message
        Publish order events from the stream as trade updates.
    on_error
        Log a stream error.
    on_close
        Log the closing of the stream.
    run
        Start the listener and heartbeat thread (overrides Trader).
    close
        Stop the listener and heartbeat thread (overrides Trader).
    get_tradeable_symbols
        Return the symbols traded on Gemini (overrides Trader).
    get_shortable_symbols
        Return an empty list (overrides Trader).
    is_shortable
        Return False (overrides Trader).
    cancel_order
        Request the cancellation of an order (overrides Trader).
    submit_order
        Submit an exchange limit order (overrides Trader).
    """

    def __init__(self, config: GeminiConfig, qm: SymbolQueueMap = None):
        """Initialize the trader with no listener running.

        Register the trader as the current Trader instance.

        Parameters
        ----------
        config: GeminiConfig
            The connection settings.
        qm: QueueMapper, default None
            The queue mapper that receives trade updates.
        """
        self.config = config
        self.running_task: Optional[asyncio.Task] = None
        self.hb_task: Optional[Thread] = None
        self.send_hb = True
        self.ws: Optional[websocket.WebSocketApp] = None
        self.flags: Optional[ThreadFlags] = None
        self.last_nonce: Optional[int] = None
        super().__init__(qm)

    def _generate_request_headers(self, payload: Dict) -> Dict:
        """Return signed headers for an authenticated REST request.

        Parameters
        ----------
        payload: Dict
            The request payload to sign; modified in place.

        Raises
        ------
        Raise AssertionError if the API key or secret is not set.
        """
        if not self.config.api_secret or not self.config.api_key:
            raise AssertionError(
                "both env variables GEMINI_API_KEY and GEMINI_API_SECRET must be set up"
            )
        payload_nonce = int(clock.now().timestamp() * 1000)

        if self.last_nonce and self.last_nonce >= payload_nonce:
            payload_nonce = self.last_nonce + 1

        self.last_nonce = payload_nonce

        payload["nonce"] = str(payload_nonce)
        encoded_payload = json.dumps(payload).encode()
        b64 = base64.b64encode(encoded_payload)
        signature = hmac.new(
            self.config.api_secret.encode(), b64, hashlib.sha384
        ).hexdigest()

        return {
            "Content-Type": "text/plain",
            "Content-Length": "0",
            "X-GEMINI-APIKEY": self.config.api_key,
            "X-GEMINI-PAYLOAD": b64,
            "X-GEMINI-SIGNATURE": signature,
            "Cache-Control": "no-cache",
        }

    def _generate_ws_headers(self, payload: Dict) -> Dict:
        """Return signed headers for the order event WebSocket connection.

        Parameters
        ----------
        payload: Dict
            The connection payload to sign; modified in place.

        Raises
        ------
        Raise AssertionError if the API key or secret is not set.
        """
        if not self.config.api_secret or not self.config.api_key:
            raise AssertionError(
                "both env variables GEMINI_API_KEY and GEMINI_API_SECRET must be set up"
            )
        payload["nonce"] = str(int(clock.now().timestamp() * 1000))
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

    @classmethod
    def _get_order_event_type(cls, order_data: Dict) -> Order.EventType:
        """Return the event type for a Gemini order status.

        Parameters
        ----------
        order_data: Dict
            An order status returned by the Gemini REST API.
        """
        return (
            Order.EventType.canceled
            if order_data["is_cancelled"] == True
            else (
                Order.EventType.fill
                if order_data["remaining_amount"] == "0"
                else Order.EventType.partial_fill
            )
        )

    @classmethod
    def _get_trade_event_type(cls, trade_data: Dict) -> Order.EventType:
        """Return the event type for a Gemini order event.

        Report a cancel_rejected event as canceled.

        Parameters
        ----------
        trade_data: Dict
            An order event received from the WebSocket stream.
        """
        if trade_data["type"] in ("cancelled", "cancel_rejected"):
            return Order.EventType.canceled
        if trade_data["type"] == "rejected":
            return Order.EventType.rejected
        if trade_data["remaining_amount"] == "0":
            return Order.EventType.fill
        return Order.EventType.partial_fill

    @classmethod
    def _get_order_side(cls, order_data: Dict) -> Order.FillSide:
        """Return the fill side of a Gemini order.

        Parameters
        ----------
        order_data: Dict
            An order returned by the Gemini REST API.
        """
        return (
            Order.FillSide.buy
            if order_data["side"] == "buy"
            else Order.FillSide.sell
        )

    @classmethod
    def _order_from_dict(cls, order_data: Dict) -> Order:
        """Return an Order built from a Gemini order status.

        The trade fees are the total fees of the trades that the status
        includes.

        Parameters
        ----------
        order_data: Dict
            An order status returned by the Gemini REST API.
        """
        trades = order_data.get("trades", [])
        trade_fees: float = 0.0 + sum(float(t["fee_amount"]) for t in trades)
        return Order(
            order_id=order_data["order_id"],
            symbol=order_data["symbol"].lower(),
            filled_qty=float(order_data["executed_amount"]),
            event=cls._get_order_event_type(order_data),
            price=float(order_data["price"]),
            side=cls._get_order_side(order_data),
            submitted_at=pd.Timestamp(
                order_data["timestampms"], unit="ms", tz="UTC"
            ).tz_convert(clock.NY),
            avg_execution_price=float(order_data["avg_execution_price"]),
            remaining_amount=float(order_data["remaining_amount"]),
            trade_fees=trade_fees,
        )

    @classmethod
    def _trade_from_dict(cls, trade_dict: Dict) -> Trade:
        """Return a Trade built from a Gemini order event, and log the event.

        Values missing from the event are reported as zero or an empty string.

        Parameters
        ----------
        trade_dict: Dict
            An order event received from the WebSocket stream.
        """
        logger.info("GEMINI GOING TO SEND %s", trade_dict)
        return Trade(
            order_id=trade_dict["order_id"],
            symbol=trade_dict["symbol"].lower(),
            event=cls._get_trade_event_type(trade_dict),
            filled_qty=(
                float(trade_dict["fill"]["amount"])
                if "fill" in trade_dict
                else 0.0
            ),
            trade_fee=(
                float(
                    trade_dict["fill"]["fee"] if "fill" in trade_dict else 0.0
                )
                if "fill" in trade_dict
                else 0.0
            ),
            filled_avg_price=float(trade_dict["avg_execution_price"] or 0.0),
            liquidity=(
                trade_dict["fill"]["liquidity"] if "fill" in trade_dict else ""
            ),
            updated_at=pd.Timestamp(
                trade_dict["timestampms"], unit="ms", tz="UTC"
            ).tz_convert(clock.NY),
            side=Order.FillSide[trade_dict["side"]],
        )

    async def is_fractionable(self, symbol: str) -> bool:
        """Return True, since every symbol is treated as fractionable.

        Parameters
        ----------
        symbol: str
            The symbol to check; ignored.
        """
        return True

    def _check_error(self, result: Dict):
        """Raise AssertionError if a Gemini API response reports an error.

        Parameters
        ----------
        result: Dict
            A decoded JSON response from the Gemini REST API.
        """
        if result.get("result") == "error":
            raise AssertionError(
                f"[EXCEPTION] {result['reason']}:{result['message']}"
            )

    async def is_order_completed(
        self, order_id: str, external_order_id: Optional[str] = None
    ) -> Tuple[
        Order.EventType, Optional[float], Optional[float], Optional[float]
    ]:
        """Return the status, average price, quantity and fees of an order.

        Parameters
        ----------
        order_id: str
            The Gemini order identifier.
        external_order_id: Optional[str], default None
            Ignored.

        Raises
        ------
        Raise AssertionError if Gemini reports an error.
        """
        order = await self.get_order(order_id)
        return (
            order.event,
            order.avg_execution_price,
            order.filled_qty,
            order.trade_fees,
        )

    def get_market_schedule(
        self,
    ) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """Return the start and end of today in New York as the session.

        The session runs from midnight to 23:59:59.
        """
        start = pd.Timestamp(clock.today(), tz=clock.NY)
        return start, start.replace(hour=23, minute=59, second=59)

    def get_trading_days(
        self, start_date: date, end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """Return a DataFrame indexed by every calendar day in a range.

        The DataFrame has no columns, and its index, named date, holds dates.

        Parameters
        ----------
        start_date: date
            The first day of the range.
        end_date: Optional[date], default None
            The last day of the range, or None for today in New York.
        """
        days = pd.date_range(start=start_date, end=end_date or clock.today())
        return pd.DataFrame(index=pd.Index(days.date, name="date"))

    def get_position(self, symbol: str) -> float:
        """Return the account balance held in a currency.

        Parameters
        ----------
        symbol: str
            The currency to look up.

        Returns
        -------
        Return zero if no balance is held.

        Raises
        ------
        Raise AssertionError if the request fails.
        """
        symbol = symbol.lower()
        endpoint = "/v1/balances"
        url = self.config.trading_base_url + endpoint

        payload = {
            "request": endpoint,
        }
        headers = self._generate_request_headers(payload)
        response = requests.post(url, data=None, headers=headers)

        if response.status_code == 200:
            return next(
                (
                    float(b["amount"])
                    for b in response.json()
                    if b["currency"] == symbol
                ),
                0.0,
            )

        raise AssertionError(
            f"HTTP ERROR {response.status_code} {response.text}"
        )

    async def get_order(
        self, order_id: str, client_order_id: Optional[str] = None
    ) -> Order:
        """Return the current state of an order.

        Parameters
        ----------
        order_id: str
            The Gemini order identifier.
        client_order_id: Optional[str], default None
            Ignored.

        Raises
        ------
        Raise AssertionError if Gemini reports an error.
        """
        endpoint = "/v1/order/status"
        url = self.config.trading_base_url + endpoint

        payload = {
            "request": endpoint,
            "order_id": order_id,
            "include_trades": True,
        }
        headers = self._generate_request_headers(payload)
        response = requests.post(url, data=None, headers=headers)

        if response.status_code == 200:
            order_data = response.json()
            self._check_error(order_data)

            return self._order_from_dict(order_data)

        raise AssertionError(
            f"HTTP ERROR {response.status_code} {response.text}"
        )

    def is_market_open_today(self) -> bool:
        """Return True, since the market is treated as open every day."""
        return True

    def get_time_market_close(self) -> Optional[pd.Timedelta]:
        """Return the time remaining until 23:59:59 today in New York."""
        now = clock.now()
        return (
            now.replace(
                hour=23, minute=59, second=59, microsecond=0, nanosecond=0
            )
            - now
        )

    async def reconnect(self):
        """Restart the order event listener and heartbeat thread."""
        await self.close()
        await self.run()

    def _heartbeat(self, flags: ThreadFlags):
        """Send heartbeats to Gemini until flags.run is cleared.

        Block until stopped, so run it in a dedicated thread.

        Parameters
        ----------
        flags: ThreadFlags
            The thread flags whose run attribute keeps the heartbeat going.

        Raises
        ------
        Raise AssertionError if a heartbeat fails.
        """
        logger.info("GEMINI HEARTBEAT thread starting")
        while flags.run:
            logger.debug("GEMINI HEARTBEAT")
            endpoint = "/v1/heartbeat"
            url = self.config.trading_base_url + endpoint

            payload = {
                "request": endpoint,
            }
            headers = self._generate_request_headers(payload)
            response = requests.post(url, data=None, headers=headers)

            if response.status_code != 200:
                raise AssertionError(
                    f"HEARTHBEAT HTTP ERROR {response.status_code} {response.text}"
                )

            time.sleep(20)

        logger.info("GEMINI HEARTBEAT thread terminated")

    @classmethod
    def on_message(cls, ws, msgs):
        """Publish order events from the Gemini stream as trade updates.

        Log each fill, cancelled, cancel_rejected or rejected event and put it
        as a trade update on every queue of the current trader.

        Parameters
        ----------
        ws
            The WebSocket application; unused.
        msgs
            The raw JSON text of a stream message.

        Raises
        ------
        Raise queue.Full if a queue stays full.
        """
        msgs = json.loads(msgs)
        if type(msgs) != list:
            return

        for msg in msgs:
            if msg["type"] in [
                "fill",
                "cancel_rejected",
                "cancelled",
                "rejected",
            ]:
                trade = cls._trade_from_dict(msg)
                symbol = trade.symbol.lower()
                logger.info("GEMINI TRADING UPDATE:%s", trade)
                to_send = {
                    "EV": QueueMessageType.TRADE_UPDATE,
                    "symbol": symbol,
                    "trade": trade.__dict__,
                }
                try:
                    if qs := cls.get_instance().queues:
                        for q in qs.get_allqueues():
                            q.put(to_send, timeout=1)
                except queue.Full as f:
                    logger.error(
                        "queue for %s is FULL:%s, sleeping for 2 seconds and re-trying.",
                        symbol,
                        f,
                    )
                    raise

    @classmethod
    def on_error(cls, ws, error):
        """Log an error reported by the WebSocket connection.

        Parameters
        ----------
        ws
            The WebSocket application; unused.
        error
            The reported error.
        """
        logger.error("GeminiTrader %s", error)

    @classmethod
    def on_close(cls, ws, close_status_code, close_msg):
        """Log the closing of the WebSocket connection.

        Parameters
        ----------
        ws
            The WebSocket application; unused.
        close_status_code
            The close status code.
        close_msg
            The close message.
        """
        logger.info(
            "on_close(): status=%s, close_msg=%s", close_status_code, close_msg
        )

    async def run(self) -> asyncio.Task:
        """Start the order event listener and the heartbeat thread.

        The blocking WebSocket client runs in a thread, wrapped in a task.

        Returns
        -------
        Return the listener task; if it already exists, return it without
        starting another.

        Raises
        ------
        Raise AssertionError if the API key or secret is not set.
        """
        if not self.running_task:
            logger.info("starting Gemini listener")
            endpoint = "/v1/order/events"
            payload = {"request": endpoint}
            headers = self._generate_ws_headers(payload)
            self.ws = websocket.WebSocketApp(
                f"{self.config.trading_base_websocket}{endpoint}?eventTypeFilter=cancel_rejected&eventTypeFilter=cancelled&eventTypeFilter=rejected&eventTypeFilter=fill&eventTypeFilter=closed&heartbeat=true",
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                header=headers,
            )
            self.running_task = asyncio.create_task(
                asyncio.to_thread(
                    self.ws.run_forever, sslopt={"cert_reqs": ssl.CERT_NONE}
                )
            )
            self.flags = ThreadFlags(run=True)
            self.hb_task = Thread(target=self._heartbeat, args=(self.flags,))
            self.hb_task.start()

        return self.running_task

    async def close(self):
        """Stop the listener and heartbeat thread if the listener is running.

        Wait until both have finished.
        """
        if self.running_task and not self.running_task.done():
            logger.info("close task %s", self.running_task)
            self.ws.keep_running = False
            self.flags.run = False
            await self.running_task
            await asyncio.to_thread(self.hb_task.join)
            logger.info("task terminated")
            self.ws = None
            self.running_task = None
            self.hb_task = None
            self.flags = None

    async def get_tradeable_symbols(self) -> List[str]:
        """Return the symbols that can be traded on Gemini.

        Raises
        ------
        Raise AssertionError if the request fails.
        """
        endpoint = "/v1/symbols"
        url = self.config.trading_base_url + endpoint
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()

        raise AssertionError(
            f"HTTP ERROR {response.status_code} {response.text}"
        )

    async def get_shortable_symbols(self) -> List[str]:
        """Return an empty list, since short selling is not supported."""
        return []

    async def is_shortable(self, symbol) -> bool:
        """Return False, since short selling is not supported.

        Parameters
        ----------
        symbol
            The symbol to check; ignored.
        """
        return False

    async def cancel_order(self, order: Order) -> bool:
        """Request the cancellation of an order.

        Parameters
        ----------
        order: Order
            The order to cancel.

        Returns
        -------
        Return the status of the canceled order as reported by Gemini.

        Raises
        ------
        Raise AssertionError if Gemini reports an error.
        """
        endpoint = "/v1/order/cancel"
        url = self.config.trading_base_url + endpoint

        payload = {"request": endpoint, "order_id": order.order_id}
        headers = self._generate_request_headers(payload)
        response = requests.post(url, data=None, headers=headers)
        if response.status_code == 200:
            order_status = response.json()
            self._check_error(order_status)
            return order_status

        raise AssertionError(
            f"HTTP ERROR {response.status_code} {response.text}"
        )

    async def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: OrderType,
        time_in_force: str = None,
        limit_price: Optional[str] = None,
        stop_price: str = None,
        client_order_id: str = None,
        extended_hours: bool = None,
        order_class: str = None,
        take_profit: dict = None,
        stop_loss: dict = None,
        trail_price: str = None,
        trail_percent: str = None,
        on_behalf_of: str = None,
    ) -> Order:
        """Submit an exchange limit order to Gemini.

        A failed request also stops the listener and heartbeat thread.

        Parameters
        ----------
        symbol: str
            The asset symbol.
        qty: float
            The quantity, rounded to the precision of the asset.
        side: str
            Buy or sell.
        order_type: OrderType
            The order type; market orders are rejected.
        time_in_force: str, default None
            Ignored.
        limit_price: Optional[str], default None
            The price of a limit order; other order types get a placeholder
            price.
        stop_price: str, default None
            Ignored.
        client_order_id: str, default None
            The client identifier of the order.
        extended_hours: bool, default None
            Ignored.
        order_class: str, default None
            Ignored.
        take_profit: dict, default None
            Ignored.
        stop_loss: dict, default None
            Ignored.
        trail_price: str, default None
            Ignored.
        trail_percent: str, default None
            Ignored.
        on_behalf_of: str, default None
            Ignored.

        Returns
        -------
        Return the new order.

        Raises
        ------
        Raise AssertionError for a market order, a quantity below the asset
        minimum or an error from Gemini, and ValueError for an unknown asset.
        """
        symbol = symbol.lower()
        if order_type == OrderType.MARKET:
            raise AssertionError(
                "GEMINI does not support market orders, use limit orders"
            )

        if qty < get_asset_min_qty(symbol):
            raise AssertionError(
                f"GEMINI requested quantity of {qty} is below minimum for {symbol}"
            )

        endpoint = "/v1/order/new"
        url = self.config.trading_base_url + endpoint
        qty = round_asset(symbol, qty)
        payload: Dict = {
            "request": endpoint,
            "symbol": symbol,
            "amount": str(qty),
            "price": (
                limit_price
                if order_type == OrderType.LIMIT
                else str(60000.0 * qty)
            ),
            "side": side,
            "type": GeminiOrderType.EXCHANGE_LIMIT.value,
            "client_order_id": client_order_id,
            "options": (
                ["immediate-or-cancel"]
                if order_type == OrderType.MARKET
                else []
            ),
        }

        headers = self._generate_request_headers(payload)
        response = requests.post(url, data=None, headers=headers)

        if response.status_code == 200:
            new_order = response.json()
            self._check_error(new_order)
            return self._order_from_dict(new_order)

        if self.flags:
            self.flags.run = False

        await self.close()

        raise AssertionError(
            f"HTTP ERROR {response.status_code} {response.text}"
        )
