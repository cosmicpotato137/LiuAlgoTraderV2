"""Tradier brokerage trader.

Classes
-------
TradierOrderType
    Enumeration of the Tradier equity order types.
TradierTrader
    Trader implementation for the Tradier brokerage.
"""

import asyncio
import json
import logging
import queue
import time as time_action
from datetime import date, time
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
from liualgotrader.vendors.tradier.config import TradierConfig

logger = logging.getLogger(__name__)

# The Order.EventType of each Tradier order status that is not other.
_STATUS_EVENTS = {
    "filled": Order.EventType.fill,
    "partially_filled": Order.EventType.partial_fill,
    "canceled": Order.EventType.canceled,
    "rejected": Order.EventType.rejected,
    "pending": Order.EventType.pending,
    "error": Order.EventType.error,
    "open": Order.EventType.open,
}


class TradierOrderType(StrEnum):
    """Enumeration of the Tradier equity order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


# The Tradier order type of each OrderType that Tradier supports.
_TRADIER_ORDER_TYPES = {
    OrderType.MARKET: TradierOrderType.MARKET,
    OrderType.LIMIT: TradierOrderType.LIMIT,
    OrderType.STOP: TradierOrderType.STOP,
    OrderType.STOP_LIMIT: TradierOrderType.STOP_LIMIT,
}


class TradierTrader(TraderAPI):
    """Trader implementation for the Tradier brokerage.

    Orders are whole-share equity day orders, no symbol is fractionable, and
    only orders submitted through this class produce trade updates.

    Attributes
    ----------
    config: TradierConfig
        The connection settings, including the account number.
    running_task: Optional[Thread]
        The account event listener thread, or None.
    ws: Optional[websocket]
        The account event WebSocket application, or None.
    ws_session_id: Optional[str]
        The streaming session identifier, or None.

    Methods
    -------
    is_fractionable
        Return False for every symbol (overrides Trader).
    is_order_completed
        Return the status, price and quantity of an order (overrides Trader).
    get_market_schedule
        Return today's extended trading window (overrides Trader).
    get_trading_days
        Return the open days in a range (overrides Trader).
    get_position
        Return the quantity held of a symbol (overrides Trader).
    get_order
        Return the current state of an order (overrides Trader).
    is_market_open_today
        Report whether the market opens today (overrides Trader).
    get_time_market_close
        Return the time left until today's close (overrides Trader).
    get_tradeable_symbols
        Return the easy-to-borrow stocks (overrides Trader).
    get_shortable_symbols
        Return the easy-to-borrow stocks (overrides Trader).
    is_shortable
        Report whether a symbol is easy to borrow (overrides Trader).
    cancel_order
        Request the cancellation of an order (overrides Trader).
    _subscribe_order_status_update
        Subscribe the stream to order events.
    submit_order
        Submit an equity day order (overrides Trader).
    reconnect
        Restart the account event listener (overrides Trader).
    run
        Start the account event listener (overrides Trader).
    close
        Stop the account event listener (overrides Trader).
    on_message
        Publish order events from the stream as trade updates.
    on_error
        Log a stream error.
    on_close
        Log the closing of the stream.
    """

    order_symbol: Dict[int, str] = {}
    order_side: Dict[int, Order.FillSide] = {}

    def __init__(self, config: TradierConfig, qm: SymbolQueueMap = None):
        """Initialize the trader with no listener running.

        Register the trader as the current Trader instance.

        Parameters
        ----------
        config: TradierConfig
            The connection settings.
        qm: QueueMapper, default None
            The queue mapper that receives trade updates.
        """
        self.config = config
        self.running_task: Optional[Thread] = None
        self.ws: Optional[websocket] = None
        self.ws_session_id: Optional[str] = None
        super().__init__(qm)

    def _get(self, url: str, params: Optional[Dict] = None):
        """Send an authenticated GET request to the Tradier API.

        Parameters
        ----------
        url: str
            The endpoint URL.
        params: Optional[Dict], default None
            The query parameters.

        Returns
        -------
        Return the response.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        if params is None:
            params = {}
        r = requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
            },
        )
        if r.status_code in (429, 502):
            logger.warning(
                "%s return %s, waiting and re-trying", r.url, r.status_code
            )
            time_action.sleep(10)
            return self._get(url, params)
        elif r.status_code != 200:
            raise ValueError(f"HTTP ERROR {r.url} {r.status_code} {r.text}")

        return r

    def _post(self, url: str, params: Optional[Dict] = None):
        """Send an authenticated POST request to the Tradier API.

        Parameters
        ----------
        url: str
            The endpoint URL.
        params: Optional[Dict], default None
            The query parameters.

        Returns
        -------
        Return the response.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        if params is None:
            params = {}
        r = requests.post(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
            },
        )
        if r.status_code in (429, 502):
            logger.warning(
                "%s return %s, waiting and re-trying", r.url, r.status_code
            )
            time_action.sleep(10)
            return self._post(url, params)
        elif r.status_code != 200:
            raise ValueError(f"HTTP ERROR {r.url} {r.status_code} {r.text}")

        return r

    def _delete(self, url: str, params: Optional[Dict] = None):
        """Send an authenticated DELETE request to the Tradier API.

        Parameters
        ----------
        url: str
            The endpoint URL.
        params: Optional[Dict], default None
            The query parameters.

        Returns
        -------
        Return the response.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        if params is None:
            params = {}
        r = requests.delete(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
            },
        )
        if r.status_code in (429, 502):
            logger.warning(
                "%s return %s, waiting and re-trying", r.url, r.status_code
            )
            time_action.sleep(10)
            return self._delete(url, params)
        elif r.status_code != 200:
            raise ValueError(f"HTTP ERROR {r.url} {r.status_code} {r.text}")

        return r

    async def is_fractionable(self, symbol: str) -> bool:
        """Return False, since fractional shares are not supported.

        Parameters
        ----------
        symbol: str
            The symbol to check; ignored.
        """
        return False

    async def is_order_completed(
        self, order_id: str, external_order_id: Optional[str] = None
    ) -> Tuple[Order.EventType, float, float, float]:
        """Return the status, average price, quantity and fees of an order.

        The fee is always zero, and a missing price or quantity is reported as
        zero.

        Parameters
        ----------
        order_id: str
            The Tradier order identifier.
        external_order_id: Optional[str], default None
            Ignored.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        order = await self.get_order(order_id, external_order_id)
        return (
            order.event,
            float(order.avg_execution_price or 0.0),
            float(order.filled_qty or 0.0),
            0.0,
        )

    def get_market_schedule(
        self,
    ) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """Return today's trading window.

        The window runs from 07:00 to 19:55:59.999999.

        Returns
        -------
        Return two None values if the Tradier market clock reports a date
        other than today in New York.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}markets/clock"
        response = self._get(
            url,
        )
        data = response.json()

        last_open_date = date.fromisoformat(data["clock"]["date"])
        if last_open_date != clock.today():
            return None, None

        return (
            pd.Timestamp.combine(last_open_date, time(hour=7)).tz_localize(
                clock.NY
            ),
            pd.Timestamp.combine(
                last_open_date,
                time(hour=19, minute=55, second=59, microsecond=999999),
            ).tz_localize(clock.NY),
        )

    def get_trading_days(
        self, start_date: date, end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """Return the open trading days in a date range with their hours.

        The DataFrame is indexed by date, in an index named date, with the
        premarket start in the open column and the postmarket end, or the
        regular close, in the close column.

        Parameters
        ----------
        start_date: date
            The first day of the range.
        end_date: Optional[date], default None
            The last day of the range, or None for today in New York.

        Raises
        ------
        Raise ValueError if a request fails.
        """
        end_date = end_date or clock.today()
        url = f"{self.config.base_url}markets/calendar"
        d = start_date
        df = pd.DataFrame()

        while True:
            response = self._get(
                url, params={"month": d.month, "year": d.year}
            )

            # Tradier lists the session hours as New York times of the day
            open_days = [
                day
                for day in response.json()["calendar"]["days"]["day"]
                if day["status"] == "open"
                and start_date <= date.fromisoformat(day["date"]) <= end_date
            ]
            df1 = pd.DataFrame(
                {
                    "open": [
                        pd.Timestamp(
                            f"{day['date']} {day['premarket']['start']}",
                            tz=clock.NY,
                        )
                        for day in open_days
                    ],
                    "close": [
                        pd.Timestamp(
                            f"{day['date']} "
                            f"{day.get('postmarket', day['open'])['end']}",
                            tz=clock.NY,
                        )
                        for day in open_days
                    ],
                },
                index=pd.Index(
                    [date.fromisoformat(day["date"]) for day in open_days],
                    name="date",
                ),
            )
            df = pd.concat([df, df1])
            if d.month == end_date.month and d.year == end_date.year:
                break

            d = date(d.year + d.month // 12, d.month % 12 + 1, 1)

        return df

    def get_position(self, symbol: str) -> float:
        """Return the quantity of a symbol held in the account.

        Parameters
        ----------
        symbol: str
            The symbol to look up.

        Returns
        -------
        Return zero if no position is held.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}accounts/{self.config.account_number}/positions"
        response = self._get(
            url,
        )
        data = response.json()
        if data["positions"] == "null":
            return 0.0

        data = data["positions"]["position"]
        if isinstance(data, dict):
            return data["quantity"] if data["symbol"] == symbol else 0.0

        return next(
            (
                position["quantity"]
                for position in data
                if position["symbol"] == symbol
            ),
            0.0,
        )

    @classmethod
    def _get_event(cls, order_event: str) -> Order.EventType:
        """Return the event type for a Tradier order status.

        Parameters
        ----------
        order_event: str
            The Tradier order status.

        Returns
        -------
        Return the other event type for an unrecognized status.
        """
        return _STATUS_EVENTS.get(order_event, Order.EventType.other)

    async def get_order(
        self, order_id: str, client_order_id: Optional[str] = None
    ) -> Order:
        """Return the current state of an order.

        The price is the last fill price, the fees are zero, and the order tag
        becomes the external account identifier.

        Parameters
        ----------
        order_id: str
            The Tradier order identifier.
        client_order_id: Optional[str], default None
            Ignored.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}accounts/{self.config.account_number}/orders/{order_id}"
        response = self._get(
            url,
        )
        data = response.json()
        return Order(
            order_id=data["order"]["id"],
            symbol=data["order"]["symbol"],
            event=self._get_event(data["order"]["status"]),
            submitted_at=pd.to_datetime(
                data["order"]["create_date"], utc=True
            ).tz_convert(clock.NY),
            price=data["order"]["last_fill_price"],
            trade_fees=0.0,
            filled_qty=data["order"]["exec_quantity"],
            side=self._get_event_side(data["order"]["side"]),
            remaining_amount=data["order"]["remaining_quantity"],
            avg_execution_price=data["order"]["avg_fill_price"],
            external_account_id=(
                data["order"]["tag"] if "tag" in data["order"] else None
            ),
        )

    def is_market_open_today(self) -> bool:
        """Report whether the Tradier calendar lists today as open.

        Today is the current date in New York.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}markets/calendar"
        response = self._get(
            url,
        )
        data = response.json()
        today = str(clock.today())
        return next(
            (
                day["status"] == "open"
                for day in data["calendar"]["days"]["day"]
                if day["date"] == today
            ),
            False,
        )

    def get_time_market_close(self) -> Optional[pd.Timedelta]:
        """Return the time left until today's close in the Tradier calendar.

        The close is the end of the postmarket session, or of the regular
        session when none is listed.

        Returns
        -------
        Return None if today has no session.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}markets/calendar"
        response = self._get(
            url,
        )
        data = response.json()
        now = clock.now()
        today = str(now.date())
        close = next(
            (
                day.get("postmarket", day["open"])["end"]
                for day in data["calendar"]["days"]["day"]
                if day["date"] == today and "open" in day
            ),
            None,
        )
        return (
            None
            if close is None
            else pd.Timestamp(f"{today} {close}", tz=clock.NY) - now
        )

    async def get_tradeable_symbols(self) -> List[str]:
        """Return the easy-to-borrow stocks as the tradeable symbols.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        return await self.get_shortable_symbols()

    async def get_shortable_symbols(self) -> List[str]:
        """Return the stock symbols on the Tradier easy-to-borrow list.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}markets/etb"
        response = self._get(
            url,
        )
        data = response.json()
        return [
            security["symbol"]
            for security in data["securities"]["security"]
            if security["type"] == "stock"
        ]

    async def is_shortable(self, symbol) -> bool:
        """Report whether a symbol is on the Tradier easy-to-borrow list.

        Parameters
        ----------
        symbol
            The symbol to check, in any letter case.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        return symbol.upper() in await self.get_shortable_symbols()

    async def cancel_order(self, order: Order) -> bool:
        """Request the cancellation of an order.

        Parameters
        ----------
        order: Order
            The order to cancel.

        Returns
        -------
        Return True if Tradier accepts the request.

        Raises
        ------
        Raise ValueError if the request fails.
        """
        url = f"{self.config.base_url}accounts/{self.config.account_number}/orders/{order.order_id}"

        response = self._delete(
            url,
        )
        data = response.json()
        return data["order"]["status"] == "ok"

    @classmethod
    def _get_event_side(cls, side: str) -> Order.FillSide:
        """Return the fill side for a Tradier order side.

        Report buy and buy_to_cover as buy, and every other side as sell.

        Parameters
        ----------
        side: str
            The Tradier order side.
        """
        if side in {"buy", "buy_to_cover"}:
            return Order.FillSide.buy

        return Order.FillSide.sell

    async def _subscribe_order_status_update(self) -> None:
        """Subscribe the streaming session to order status events.

        Do nothing unless the listener is running with an open session.
        """
        if (
            self.ws is not None
            and self.ws_session_id
            and self.running_task
            and self.running_task.is_alive()
        ):
            payload = {
                "events": ["order"],
                "sessionid": self.ws_session_id,
                "excludeAccounts": [],
            }
            self.ws.send(json.dumps(payload))
            logger.info(
                "subscribed for order update on session %s", self.ws_session_id
            )

    async def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: OrderType,
        time_in_force: str = None,
        limit_price: str = None,
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
        """Submit an equity day order to Tradier.

        Parameters
        ----------
        symbol: str
            The stock symbol.
        qty: float
            The quantity, truncated to whole shares.
        side: str
            The Tradier order side, such as buy or sell.
        order_type: OrderType
            The order type, such as OrderType.MARKET or OrderType.LIMIT.
        time_in_force: str, default None
            Ignored.
        limit_price: str, default None
            The limit price, rounded to cents.
        stop_price: str, default None
            The stop price, rounded to cents.
        client_order_id: str, default None
            Ignored.
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
            The external account, sent as the order tag.

        Returns
        -------
        Return the new order with a pending status, and record it so that its
        stream events become trade updates.

        Raises
        ------
        Raise ValueError if Tradier does not support the order type, the
        request fails or Tradier reports errors.
        """
        tradier_type = _TRADIER_ORDER_TYPES.get(order_type)
        if tradier_type is None:
            raise ValueError(f"unsupported Tradier order type {order_type}")

        url = f"{self.config.base_url}accounts/{self.config.account_number}/orders"

        params: Dict = {
            "class": "equity",
            "symbol": symbol,
            "side": side,
            "quantity": str(int(qty)),
            "duration": "day",
            "type": tradier_type.value,
        }

        if limit_price:
            params["price"] = str(round(float(limit_price), 2))
        if stop_price:
            params["stop"] = str(round(float(stop_price), 2))
        if on_behalf_of:
            params["tag"] = on_behalf_of

        response = self._post(
            url,
            params,
        )
        data = response.json()

        if "errors" in data:
            raise ValueError(f"order failed with {data['errors']}")

        event_side = self._get_event_side(side)
        o = Order(
            symbol=symbol,
            order_id=data["order"]["id"],
            event=Order.EventType.pending,
            side=event_side,
            submitted_at=clock.now(),
            remaining_amount=qty,
        )

        if on_behalf_of:
            o.external_account_id = on_behalf_of
        if limit_price:
            o.price = float(limit_price)

        TradierTrader.order_symbol[int(o.order_id)] = symbol
        TradierTrader.order_side[int(o.order_id)] = event_side
        return o

    async def reconnect(self):
        """Restart the account event listener."""
        await self.close()
        await self.run()

    async def run(self) -> Optional[asyncio.Task]:
        """Start the account event listener and subscribe it to order events.

        Returns
        -------
        Return the listener thread; if it already exists, return it without
        starting another.

        Raises
        ------
        Raise ValueError if no streaming session can be created.
        """
        if not self.running_task:
            logger.info("starting Tradier Account listener")

            url = f"{self.config.base_url}accounts/events/session"

            response = self._post(
                url,
            )
            data = response.json()

            ws_url = data["stream"]["url"]
            self.ws_session_id = data["stream"]["sessionid"]

            logger.info(
                "starting WebSocketApp on %s with session-id %s",
                ws_url,
                self.ws_session_id,
            )
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
            )
            self.running_task = Thread(
                target=self.ws.run_forever,
            )
            self.running_task.start()
            await asyncio.sleep(1.0)
            await self._subscribe_order_status_update()

        return self.running_task  # type: ignore

    async def close(self):
        """Stop the account event listener if it is running.

        Block until the listener thread has finished.
        """
        if self.running_task and self.running_task.is_alive():
            logger.info("close task %s", self.running_task)
            self.ws.keep_running = False
            self.running_task.join()
            logger.info("task terminated")
            self.ws = None
            self.running_task = None
            self.ws_session_id = None

    @classmethod
    def _trade_from_dict(cls, trade_dict: Dict) -> Trade:
        """Return a Trade built from a Tradier order event.

        The fee is zero, and a missing fill quantity or price is reported as
        zero.

        Parameters
        ----------
        trade_dict: Dict
            An order event received from the account stream.

        Raises
        ------
        Raise KeyError if the order was not submitted through submit_order.
        """
        return Trade(
            order_id=trade_dict["id"],
            symbol=TradierTrader.order_symbol[trade_dict["id"]],
            event=cls._get_event(trade_dict["status"]),
            side=TradierTrader.order_side[trade_dict["id"]],
            filled_qty=float(trade_dict.get("last_fill_quantity", 0.0)),
            trade_fee=0.0,
            filled_avg_price=float(trade_dict.get("last_fill_price", 0.0)),
            liquidity="",
            updated_at=pd.to_datetime(
                trade_dict["create_date"], utc=True
            ).tz_convert(clock.NY),
        )

    @classmethod
    def on_message(cls, ws, msgs):
        """Publish order events from the Tradier stream as trade updates.

        Log each filled, cancelled, cancel_rejected or rejected event of an
        order submitted through submit_order, and put it as a trade update on
        every queue of the current trader.

        Parameters
        ----------
        ws
            The WebSocket application; unused.
        msgs
            The raw JSON text of a stream event.

        Raises
        ------
        Raise queue.Full if a queue stays full.
        """
        msg = json.loads(msgs)

        if msg["event"] != "order":
            return

        if (
            msg["status"]
            in {
                "filled",
                "cancel_rejected",
                "cancelled",
                "rejected",
            }
            and msg["id"] in TradierTrader.order_symbol
        ):
            trade = cls._trade_from_dict(msg)
            symbol = trade.symbol.lower()
            logger.info("TRADIER TRADING UPDATE:%s", trade)
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
        logger.error("TradierTrader %s", error)

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
            "on_close(): TradierTrader status=%s, close_msg=%s",
            close_status_code,
            close_msg,
        )
