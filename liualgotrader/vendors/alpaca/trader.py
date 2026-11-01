"""Alpaca brokerage trader.

Classes
-------
AlpacaTrader
    Trader implementation for the Alpaca brokerage.
"""

import asyncio
import logging
import queue
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import pandas as pd
import requests
from alpaca.common.enums import BaseURL
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus
from alpaca.trading.enums import OrderType as AlpacaOrderType
from alpaca.trading.enums import PositionSide
from alpaca.trading.models import Asset, Calendar
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position, TradeUpdate
from alpaca.trading.requests import (GetCalendarRequest, LimitOrderRequest,
                                     MarketOrderRequest, OrderRequest,
                                     StopLimitOrderRequest, StopLossRequest,
                                     StopOrderRequest, TakeProfitRequest,
                                     TrailingStopOrderRequest)
from alpaca.trading.stream import TradingStream
from requests.auth import HTTPBasicAuth

from liualgotrader.common import clock
from liualgotrader.common.types import (Order, OrderType, QueueMessageType,
                                        SymbolQueueMap, Trade)
from liualgotrader.trade.base import TraderAPI
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.alpaca.util import alpaca_time

logger = logging.getLogger(__name__)

# How many times to try putting a trade update on a full consumer queue, and
# how many seconds to sleep between tries.
_QUEUE_PUT_ATTEMPTS = 3
_QUEUE_FULL_RETRY_SECONDS = 2


def _enum_value(field: Union[Enum, str, None]) -> str:
    """Return the string form of an alpaca-py enum or string field.

    Parameters
    ----------
    field: Union[Enum, str, None]
        The field value, such as an OrderStatus or a plain string.

    Returns
    -------
    Return an empty string for None.
    """
    if isinstance(field, Enum):
        return str(field.value)
    return field or ""


# The Order.EventType of each Alpaca order status that is not other.
_STATUS_EVENTS = {
    "canceled": Order.EventType.canceled,
    "expired": Order.EventType.canceled,
    "replaced": Order.EventType.canceled,
    "pending_cancel": Order.EventType.pending,
    "pending_replace": Order.EventType.pending,
    "filled": Order.EventType.fill,
    "partially_filled": Order.EventType.partial_fill,
}

# The Order.EventType of each Alpaca trade update event that is not other.
_TRADE_EVENTS = {
    "canceled": Order.EventType.canceled,
    "suspended": Order.EventType.canceled,
    "expired": Order.EventType.canceled,
    "cancel_rejected": Order.EventType.canceled,
    "rejected": Order.EventType.rejected,
    "fill": Order.EventType.fill,
    "partial_fill": Order.EventType.partial_fill,
}

# The Alpaca order type of each OrderType.
_ALPACA_ORDER_TYPES = {
    OrderType.MARKET: AlpacaOrderType.MARKET,
    OrderType.LIMIT: AlpacaOrderType.LIMIT,
    OrderType.STOP: AlpacaOrderType.STOP,
    OrderType.STOP_LIMIT: AlpacaOrderType.STOP_LIMIT,
    OrderType.TRAILING_STOP: AlpacaOrderType.TRAILING_STOP,
}


def _status_to_event(status: Union[Enum, str, None]) -> Order.EventType:
    """Return the Order.EventType that corresponds to an Alpaca order status.

    Expired and replaced orders are reported as canceled.

    Parameters
    ----------
    status: Union[Enum, str, None]
        The Alpaca order status.
    """
    return _STATUS_EVENTS.get(_enum_value(status), Order.EventType.other)


def _is_paper(base_url: str) -> bool:
    """Return True if base_url is an Alpaca paper trading URL.

    Parameters
    ----------
    base_url: str
        The trading API base URL.
    """
    return "paper" in base_url


def _seconds_until(epoch_seconds: str) -> float:
    """Return the seconds from now until a Unix time, or zero if it passed.

    Parameters
    ----------
    epoch_seconds: str
        The Unix time in seconds, as sent in an Alpaca rate-limit header.
    """
    reset = pd.Timestamp(int(epoch_seconds), unit="s", tz="UTC")
    return max((reset - clock.now()).total_seconds(), 0.0)


class AlpacaTrader(TraderAPI):
    """Trader implementation for the Alpaca brokerage.

    This class implements Trader for the account of the configured Alpaca API
    key, and also trades for external brokerage accounts through the Alpaca
    Broker API. Today's session times are fixed at construction.

    Attributes
    ----------
    config: AlpacaConfig
        The connection settings.
    market_open: Optional[pd.Timestamp]
        Today's session opening time, or None.
    market_close: Optional[pd.Timestamp]
        Today's session closing time, or None.
    alpaca_rest_client: TradingClient
        The trading client for the configured account.
    alpaca_ws_client: Optional[TradingStream]
        The trade-update stream client, or None if no queue mapper was given.
    running_task: Optional[asyncio.Task]
        The listener task, or None before run.
    queues
        The queue mapper that receives trade updates, or None.

    Methods
    -------
    is_fractionable
        Return True if a symbol can be traded fractionally.
    is_order_completed
        Return the status and fill details of an order.
    get_market_schedule
        Return the session times recorded at creation.
    get_trading_days
        Return the Alpaca trading calendar for a date range.
    get_position
        Return the signed quantity held in a symbol.
    to_order
        Convert an Alpaca order into an Order.
    get_order
        Return an order in the configured account.
    is_market_open_today
        Return True if a session was recorded for today.
    get_time_market_close
        Return the time left until today's close.
    reconnect
        Replace the trading client.
    run
        Start the Alpaca trade-update listener.
    close
        Stop the Alpaca trade-update listener.
    get_tradeable_symbols
        Return the tradable Alpaca symbols.
    get_shortable_symbols
        Return the Alpaca symbols that can be shorted.
    is_shortable
        Return True if a symbol can be sold short.
    cancel_order
        Cancel an order in the account that holds it.
    submit_order
        Submit an order to Alpaca.
    trade_update_handler
        Forward a trade update to every consumer queue.
    """

    def __init__(self, config: AlpacaConfig, qm: SymbolQueueMap = None):
        """Initialize the Alpaca clients and record today's session times.

        Set market_open and market_close to None if the market does not trade
        today. Make the new trader the shared instance.

        Parameters
        ----------
        config: AlpacaConfig
            The connection settings.
        qm: QueueMapper, default None
            The queue mapper that receives trade updates, or None for no stream
            client.

        Raises
        ------
        Raise ValueError if the Alpaca API key or secret is not configured,
        and alpaca.common.exceptions.APIError if the calendar request fails.
        """
        self.config = config
        self.market_open: Optional[pd.Timestamp]
        self.market_close: Optional[pd.Timestamp]

        self.alpaca_rest_client: TradingClient = self._create_rest_client()
        self.alpaca_ws_client: Optional[TradingStream] = None
        if qm:
            base_url = self._trading_base_url()
            self.alpaca_ws_client = TradingStream(
                api_key=config.api_key,
                secret_key=config.api_secret,
                paper=_is_paper(base_url),
                url_override=f"{base_url.replace('http', 'ws', 1)}/stream",
            )
            self.alpaca_ws_client.subscribe_trade_updates(
                AlpacaTrader.trade_update_handler
            )
        self.running_task: Optional[asyncio.Task] = None

        today = clock.today()
        calendars = cast(
            List[Calendar],
            self.alpaca_rest_client.get_calendar(
                GetCalendarRequest(start=today, end=today)
            ),
        )

        if calendars and today >= calendars[0].date:
            # Calendar.open and Calendar.close are naive local times on
            # Calendar.date
            calendar = calendars[0]
            self.market_open = pd.Timestamp(calendar.open).tz_localize(
                clock.NY
            )
            self.market_close = pd.Timestamp(calendar.close).tz_localize(
                clock.NY
            )
        else:
            self.market_open = self.market_close = None
        super().__init__(qm)

    def _trading_base_url(self) -> str:
        """Return the configured trading API base URL.

        Returns
        -------
        Return the URL without a trailing slash or API version, or the live
        trading URL if config.base_url is not set.
        """
        base_url = self.config.base_url or BaseURL.TRADING_LIVE.value
        return base_url.rstrip("/").removesuffix("/v2")

    def _create_rest_client(self) -> TradingClient:
        """Return a trading client for the configured account and base URL."""
        base_url = self._trading_base_url()
        return TradingClient(
            api_key=self.config.api_key,
            secret_key=self.config.api_secret,
            paper=_is_paper(base_url),
            url_override=base_url,
        )

    async def _is_personal_order_completed(
        self, order_id: str
    ) -> Tuple[Order.EventType, float, float, float]:
        """Return the status and fills of an order in the configured account.

        Parameters
        ----------
        order_id: str
            The Alpaca order identifier.

        Returns
        -------
        Return the same tuple as is_order_completed.
        """
        alpaca_order = cast(
            AlpacaOrder,
            self.alpaca_rest_client.get_order_by_id(order_id=order_id),
        )
        return (
            _status_to_event(alpaca_order.status),
            float(alpaca_order.filled_avg_price or 0.0),
            float(alpaca_order.filled_qty or 0.0),
            0.0,
        )

    async def is_fractionable(self, symbol: str) -> bool:
        """Return True if Alpaca permits fractional trading of symbol.

        Parameters
        ----------
        symbol: str
            The asset symbol.

        Returns
        -------
        Return False if the asset cannot be looked up.
        """
        try:
            asset_details = cast(
                Asset, self.alpaca_rest_client.get_asset(symbol)
            )
        except Exception:
            return False

        return asset_details.fractionable

    async def _is_brokerage_account_order_completed(
        self, order_id: str, external_order_id: Optional[str] = None
    ) -> Tuple[Order.EventType, float, float, float]:
        """Return the status and fills of an order in a brokerage account.

        Parameters
        ----------
        order_id: str
            The Alpaca order identifier.
        external_order_id: Optional[str], default None
            The external brokerage account that holds the order.

        Returns
        -------
        Return the same tuple as is_order_completed.

        Raises
        ------
        Raise AssertionError if the Broker API base URL is not configured or
        the request fails.
        """
        if not self.config.broker_api_base_url:
            raise AssertionError(
                "order_on_behalf can't be called, if brokerage configs incomplete"
            )

        endpoint: str = (
            f"/v1/trading/accounts/{external_order_id}/orders/{order_id}"
        )
        logger.info("_is_brokerage_account_order_completed:%s", endpoint)
        url: str = self.config.broker_api_base_url + endpoint

        response = await self._get_request(url)
        logger.info(
            "_is_brokerage_account_order_completed: response: %s", response
        )

        return (
            _status_to_event(response["status"]),
            float(response.get("filled_avg_price") or 0.0),
            float(response.get("filled_qty") or 0.0),
            0.0,
        )

    async def is_order_completed(
        self, order_id: str, external_order_id: Optional[str] = None
    ) -> Tuple[Order.EventType, float, float, float]:
        """Return the status and fill details of an order.

        Parameters
        ----------
        order_id: str
            The Alpaca order identifier.
        external_order_id: Optional[str], default None
            The external brokerage account that holds the order, or None for
            the configured account.

        Returns
        -------
        Return a tuple of the Order.EventType, the average fill price, the
        filled quantity and a zero trade fee, with missing values as zero.
        """
        return (
            await self._is_brokerage_account_order_completed(
                order_id, external_order_id
            )
            if external_order_id
            else await self._is_personal_order_completed(order_id)
        )

    def get_market_schedule(
        self,
    ) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """Return the session times recorded when the trader was created."""
        return self.market_open, self.market_close

    def get_trading_days(
        self, start_date: date, end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """Return the Alpaca trading calendar between two dates.

        Parameters
        ----------
        start_date: date
            The first date of the range.
        end_date: Optional[date], default None
            The last date of the range, inclusive, or None for today in New
            York.

        Returns
        -------
        Return a DataFrame of the other fields of the calendar entries as
        sent by Alpaca, such as the open and close times of day, indexed by
        date.
        """
        # The Calendar model drops session_open, session_close and other
        # fields, so read the raw entries to keep every column.
        calendars = self.alpaca_rest_client.get(
            "/calendar",
            GetCalendarRequest(
                start=start_date, end=end_date or clock.today()
            ).to_request_fields(),
        )
        _df = pd.DataFrame.from_dict(calendars)
        _df["date"] = pd.to_datetime(_df.date).dt.date
        return _df.set_index("date")

    def get_position(self, symbol: str) -> float:
        """Return the signed quantity held in symbol.

        Propagate the Alpaca client's exception if no position is held.

        Parameters
        ----------
        symbol: str
            The asset symbol.

        Returns
        -------
        Return a negative quantity for a short position.
        """
        pos = cast(Position, self.alpaca_rest_client.get_open_position(symbol))

        return (
            float(pos.qty)
            if pos.side == PositionSide.LONG
            else -1.0 * float(pos.qty)
        )

    def to_order(self, alpaca_order: AlpacaOrder) -> Order:
        """Convert an Alpaca order into an Order.

        The Order has the order identifier as a string, a lowercased symbol,
        the limit price or zero as its price, the submission time in New York
        time and a zero trade fee. Expired and replaced orders are
        reported as canceled.

        Parameters
        ----------
        alpaca_order: AlpacaOrder
            The order returned by the Alpaca trading client.
        """
        filled_qty = float(alpaca_order.filled_qty or 0.0)
        return Order(
            order_id=str(alpaca_order.id),
            symbol=(alpaca_order.symbol or "").lower(),
            event=_status_to_event(alpaca_order.status),
            price=float(alpaca_order.limit_price or 0.0),
            side=Order.FillSide[_enum_value(alpaca_order.side)],
            filled_qty=filled_qty,
            remaining_amount=float(alpaca_order.qty or 0.0) - filled_qty,
            submitted_at=alpaca_time(alpaca_order.submitted_at),
            avg_execution_price=(
                float(alpaca_order.filled_avg_price)
                if alpaca_order.filled_avg_price is not None
                else None
            ),
            trade_fees=0.0,
        )

    def _json_to_order(
        self,
        brokerage_response: dict,
        external_account_id: Optional[str] = None,
    ) -> Order:
        """Convert a Broker API order response into an Order.

        Fill fields as in to_order.

        Parameters
        ----------
        brokerage_response: dict
            The decoded JSON order.
        external_account_id: Optional[str], default None
            The account to record on the Order.
        """
        return Order(
            order_id=brokerage_response["id"],
            symbol=brokerage_response["symbol"].lower(),
            event=_status_to_event(brokerage_response["status"]),
            price=float(brokerage_response["limit_price"] or 0.0),
            side=Order.FillSide[brokerage_response["side"]],
            filled_qty=float(brokerage_response["filled_qty"]),
            remaining_amount=float(brokerage_response["qty"])
            - float(brokerage_response["filled_qty"]),
            submitted_at=alpaca_time(brokerage_response["submitted_at"]),
            avg_execution_price=brokerage_response["filled_avg_price"],
            trade_fees=0.0,
            external_account_id=external_account_id,
        )

    async def get_order(self, order_id: str) -> Order:
        """Return an order in the configured account.

        Parameters
        ----------
        order_id: str
            The Alpaca order identifier.
        """
        alpaca_order = self.alpaca_rest_client.get_order_by_id(order_id)
        return self.to_order(cast(AlpacaOrder, alpaca_order))

    def is_market_open_today(self) -> bool:
        """Return True if a session opening time was recorded for today."""
        return self.market_open is not None

    def get_time_market_close(self) -> Optional[pd.Timedelta]:
        """Return the time remaining until today's market close.

        Returns
        -------
        Return None if no closing time is recorded.

        Raises
        ------
        Raise AssertionError if the market does not trade today.
        """
        if not self.is_market_open_today():
            raise AssertionError("Market closed today")

        return self.market_close - clock.now() if self.market_close else None

    async def reconnect(self):
        """Replace the trading client with a new one.

        The new client uses the same base URL and keys as the original one.
        The stream client is unchanged.
        """
        self.alpaca_rest_client = self._create_rest_client()

    async def run(self) -> asyncio.Task:
        """Start the Alpaca trade-update listener unless it is running.

        The listener runs as a task in the current event loop.

        Returns
        -------
        Return the listener task.

        Raises
        ------
        Raise AssertionError if the trader was created without a queue
        mapper.
        """
        if not self.alpaca_ws_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")
        if not self.running_task:
            logger.info("starting Alpaca listener")
            # TradingStream.run() calls asyncio.run(), which cannot be used
            # inside the running loop, so schedule its coroutine directly.
            self.running_task = asyncio.create_task(
                self.alpaca_ws_client._run_forever()
            )
        return self.running_task

    async def close(self):
        """Stop the Alpaca stream client if the listener was started.

        Raises
        ------
        Raise AssertionError if the trader was created without a queue
        mapper.
        """
        if not self.alpaca_ws_client:
            raise AssertionError("Must call w/ authenticated Alpaca client")
        if self.running_task:
            await self.alpaca_ws_client.stop_ws()

    async def get_tradeable_symbols(self) -> List[str]:
        """Return the lowercased symbols of all tradable Alpaca assets."""
        data = cast(List[Asset], self.alpaca_rest_client.get_all_assets())
        return [asset.symbol.lower() for asset in data if asset.tradable]

    async def get_shortable_symbols(self) -> List[str]:
        """Return the lowercased symbols of Alpaca assets that can be shorted.

        Include only assets that are tradable, easy to borrow and shortable.
        """
        data = cast(List[Asset], self.alpaca_rest_client.get_all_assets())
        return [
            asset.symbol.lower()
            for asset in data
            if asset.tradable and asset.easy_to_borrow and asset.shortable
        ]

    async def is_shortable(self, symbol) -> bool:
        """Return True if symbol can currently be sold short on Alpaca.

        Parameters
        ----------
        symbol
            The asset symbol, in any case.

        Returns
        -------
        Return False only if the asset is marked as not tradable, not shortable
        or not easy to borrow, or is inactive.
        """
        asset = cast(Asset, self.alpaca_rest_client.get_asset(symbol.upper()))
        return (
            asset.tradable is not False
            and asset.shortable is not False
            and asset.status != AssetStatus.INACTIVE
            and asset.easy_to_borrow is not False
        )

    async def _cancel_personal_order(self, order_id: str) -> bool:
        """Cancel an order in the configured account.

        Parameters
        ----------
        order_id: str
            The Alpaca order identifier.

        Returns
        -------
        Return True; Alpaca errors propagate as exceptions.
        """
        self.alpaca_rest_client.cancel_order_by_id(order_id)
        return True

    async def _cancel_brokerage_order(
        self, account_id: str, order_id: str
    ) -> bool:
        """Cancel an order held in an external brokerage account.

        Parameters
        ----------
        account_id: str
            The external brokerage account.
        order_id: str
            The order identifier within that account.

        Returns
        -------
        Return True only if the Broker API responds with status 204.

        Raises
        ------
        Raise AssertionError if the Broker API base URL is not configured.
        """
        if not self.config.broker_api_base_url:
            raise AssertionError(
                "_cancel_brokerage_order can't be called, if brokerage configs incomplete"
            )

        endpoint: str = f"/v1/trading/accounts/{account_id}/orders/{order_id}"
        url: str = self.config.broker_api_base_url + endpoint

        response_code = await self._delete_request(url)
        logger.info(
            "cancel_brokerage_order %s,%s -> %s",
            account_id,
            order_id,
            response_code,
        )
        return response_code == 204

    async def cancel_order(self, order: Order) -> bool:
        """Cancel an order in the account that holds it.

        Parameters
        ----------
        order: Order
            The order to cancel; one with an external_account_id is canceled
            through the Alpaca Broker API.

        Returns
        -------
        Return True if the cancellation request succeeds.
        """
        if order.external_account_id:
            return await self._cancel_brokerage_order(
                order.external_account_id, order.order_id
            )

        return await self._cancel_personal_order(order.order_id)

    async def _personal_submit(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: OrderType,
        time_in_force: str,
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
        """Submit an order for the configured account.

        Prices that do not apply to the order type are ignored.

        Parameters
        ----------
        symbol: str
            The asset symbol.
        qty: float
            The order quantity.
        side: str
            The order direction, buy or sell.
        order_type: OrderType
            The order type.
        time_in_force: str
            The order duration, such as day.
        limit_price: str, default None
            The limit price, for limit and stop-limit orders.
        stop_price: str, default None
            The stop price, for stop and stop-limit orders.
        client_order_id: str, default None
            A client-assigned order identifier.
        extended_hours: bool, default None
            Whether the order may fill outside regular hours.
        order_class: str, default None
            The order class, such as bracket.
        take_profit: dict, default None
            The take-profit leg of a bracket order, with a limit_price key.
        stop_loss: dict, default None
            The stop-loss leg of a bracket order, with a stop_price key and an
            optional limit_price key.
        trail_price: str, default None
            The trailing stop offset in dollars.
        trail_percent: str, default None
            The trailing stop offset in percent.
        on_behalf_of: str, default None
            Ignored.

        Returns
        -------
        Return the submitted order as an Order.

        Raises
        ------
        Raise ValueError if the order type is not supported or the arguments
        do not form a valid order, and alpaca.common.exceptions.APIError if
        Alpaca rejects the order.
        """
        fields: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "qty": qty,
            "side": side,
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
            "extended_hours": extended_hours,
            "order_class": order_class,
            "take_profit": (
                TakeProfitRequest(**take_profit) if take_profit else None
            ),
            "stop_loss": StopLossRequest(**stop_loss) if stop_loss else None,
        }
        request: OrderRequest
        if order_type == OrderType.MARKET:
            request = MarketOrderRequest(**fields)
        elif order_type == OrderType.LIMIT:
            request = LimitOrderRequest(**fields, limit_price=limit_price)
        elif order_type == OrderType.STOP:
            request = StopOrderRequest(**fields, stop_price=stop_price)
        elif order_type == OrderType.STOP_LIMIT:
            request = StopLimitOrderRequest(
                **fields, stop_price=stop_price, limit_price=limit_price
            )
        elif order_type == OrderType.TRAILING_STOP:
            request = TrailingStopOrderRequest(
                **fields, trail_price=trail_price, trail_percent=trail_percent
            )
        else:
            raise ValueError(f"unsupported Alpaca order type {order_type}")

        o = cast(AlpacaOrder, self.alpaca_rest_client.submit_order(request))

        return self.to_order(o)

    async def _post_request(self, url: str, payload: Dict) -> Dict:
        """Send an authenticated POST request to the Alpaca Broker API.

        Parameters
        ----------
        url: str
            The full request URL.
        payload: Dict
            The request body, sent as JSON.

        Returns
        -------
        Return the decoded JSON response.

        Raises
        ------
        Retry rate-limited requests (status 429 or 504), and raise
        AssertionError for any other failed status.
        """
        response = requests.post(
            url=url,
            json=payload,
            auth=HTTPBasicAuth(
                self.config.broker_api_key, self.config.broker_api_secret
            ),
        )

        if response.status_code in (429, 504):
            if "x-ratelimit-reset" in response.headers:
                logger.info(
                    "ALPACA BROKERAGE rate-limit till %s",
                    response.headers["x-ratelimit-reset"],
                )
                await asyncio.sleep(
                    _seconds_until(response.headers["x-ratelimit-reset"])
                )
                logger.warning("ALPACA BROKERAGE going to retry")
            else:
                logger.info(
                    "ALPACA BROKERAGE push-back w/ %s and no x-ratelimit-reset header",
                    response.status_code,
                )
                await asyncio.sleep(10.0)

            return await self._post_request(url, payload)

        if response.status_code in (200, 201, 204):
            return response.json()

        raise AssertionError(
            f"HTTP ERROR {response.status_code} from ALPACA BROKERAGE API with error {response.text}"
        )

    async def _get_request(self, url: str) -> Dict:
        """Send an authenticated GET request to the Alpaca Broker API.

        Parameters
        ----------
        url: str
            The full request URL.

        Returns
        -------
        Return the decoded JSON response.

        Raises
        ------
        Retry rate-limited requests (status 429 or 504), and raise
        AssertionError for any other failed status.
        """
        response = requests.get(
            url=url,
            auth=HTTPBasicAuth(
                self.config.broker_api_key, self.config.broker_api_secret
            ),
        )

        if response.status_code in (429, 504):
            if "x-ratelimit-reset" in response.headers:
                logger.info(
                    "ALPACA BROKERAGE rate-limit till %s",
                    response.headers["x-ratelimit-reset"],
                )
                await asyncio.sleep(
                    _seconds_until(response.headers["x-ratelimit-reset"])
                )
                logger.warning("ALPACA BROKERAGE going to retry")
            else:
                logger.info(
                    "ALPACA BROKERAGE push-back w/ %s and no x-ratelimit-reset header",
                    response.status_code,
                )
                await asyncio.sleep(10.0)

            return await self._get_request(url)

        if response.status_code in (200, 201, 204):
            return response.json()

        raise AssertionError(
            f"HTTP ERROR {response.status_code} from ALPACA BROKERAGE API with error {response.text}"
        )

    async def _delete_request(self, url: str) -> int:
        """Send an authenticated DELETE request to the Alpaca Broker API.

        Retry rate-limited requests (status 429 or 504).

        Parameters
        ----------
        url: str
            The full request URL.

        Returns
        -------
        Return the HTTP status code.
        """
        response = requests.delete(
            url=url,
            auth=HTTPBasicAuth(
                self.config.broker_api_key, self.config.broker_api_secret
            ),
        )
        if response.status_code in (429, 504):
            if "x-ratelimit-reset" in response.headers:
                logger.info(
                    "ALPACA BROKERAGE rate-limit till %s",
                    response.headers["x-ratelimit-reset"],
                )
                await asyncio.sleep(
                    _seconds_until(response.headers["x-ratelimit-reset"])
                )
                logger.warning("ALPACA BROKERAGE going to retry")
            else:
                logger.info(
                    "ALPACA BROKERAGE push-back w/ %s and no x-ratelimit-reset header",
                    response.status_code,
                )
                await asyncio.sleep(10.0)

            return await self._delete_request(url)

        return response.status_code

    async def _order_on_behalf(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: OrderType,
        time_in_force: str,
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
        """Submit an order on behalf of an external brokerage account.

        Parameters
        ----------
        symbol: str
            The asset symbol.
        qty: float
            The order quantity.
        side: str
            The order direction, buy or sell.
        order_type: OrderType
            The order type, such as OrderType.MARKET or OrderType.LIMIT.
        time_in_force: str
            The order duration, such as day.
        limit_price: str, default None
            The limit price, for limit orders.
        stop_price: str, default None
            Ignored.
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
            The external brokerage account.

        Returns
        -------
        Return an Order that records on_behalf_of as its external account.

        Raises
        ------
        Raise ValueError if the order type is not supported, and
        AssertionError if the Broker API base URL is not configured or the
        request fails.
        """
        alpaca_type = _ALPACA_ORDER_TYPES.get(order_type)
        if alpaca_type is None:
            raise ValueError(f"unsupported Alpaca order type {order_type}")

        if not self.config.broker_api_base_url:
            raise AssertionError(
                "order_on_behalf can't be called, if brokerage configs incomplete"
            )

        endpoint: str = f"/v1/trading/accounts/{on_behalf_of}/orders"
        url: str = self.config.broker_api_base_url + endpoint

        payload = {
            "symbol": symbol.upper(),
            "qty": qty,
            "side": side,
            "type": alpaca_type.value,
        }

        if limit_price:
            payload["limit_price"] = limit_price
        if time_in_force:
            payload["time_in_force"] = time_in_force

        json_response: Dict = await self._post_request(
            url=url, payload=payload
        )
        logger.info("ALPACA BROKERAGE RESPONSE: %s", json_response)

        return self._json_to_order(json_response, on_behalf_of)

    async def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: OrderType,
        time_in_force: str = "day",
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
        """Submit an order to Alpaca.

        For an external account, send only the symbol, quantity, side, order
        type, limit price and time in force. For the configured account,
        ignore prices that do not apply to the order type.

        Parameters
        ----------
        symbol: str
            The asset symbol.
        qty: float
            The order quantity.
        side: str
            The order direction, buy or sell.
        order_type: OrderType
            The order type.
        time_in_force: str, default "day"
            The order duration.
        limit_price: str, default None
            The limit price, for limit orders.
        stop_price: str, default None
            The stop price, for stop orders.
        client_order_id: str, default None
            A client-assigned order identifier.
        extended_hours: bool, default None
            Whether the order may fill outside regular hours.
        order_class: str, default None
            The order class, such as bracket.
        take_profit: dict, default None
            The take-profit leg of a bracket order.
        stop_loss: dict, default None
            The stop-loss leg of a bracket order.
        trail_price: str, default None
            The trailing stop offset in dollars.
        trail_percent: str, default None
            The trailing stop offset in percent.
        on_behalf_of: str, default None
            The external brokerage account to trade for, or None for the
            configured account.

        Returns
        -------
        Return the submitted order as an Order.

        Raises
        ------
        Raise ValueError if the order type is not supported. For the
        configured account, also raise ValueError if the arguments do not
        form a valid order and alpaca.common.exceptions.APIError if Alpaca
        rejects it. For an external account, raise AssertionError if the
        request fails.
        """
        if on_behalf_of:
            return await self._order_on_behalf(
                symbol,
                qty,
                side,
                order_type,
                time_in_force,
                limit_price,
                stop_price,
                client_order_id,
                extended_hours,
                order_class,
                take_profit,
                stop_loss,
                trail_price,
                trail_percent,
                on_behalf_of,
            )
        else:
            return await self._personal_submit(
                symbol,
                qty,
                side,
                order_type,
                time_in_force,
                limit_price,
                stop_price,
                client_order_id,
                extended_hours,
                order_class,
                take_profit,
                stop_loss,
                trail_price,
                trail_percent,
                on_behalf_of,
            )

    @classmethod
    def _trade_from_dict(cls, trade_dict: TradeUpdate) -> Optional[Trade]:
        """Convert an Alpaca trade update into a Trade.

        The Trade has the order identifier as a string, a lowercased symbol
        without slashes and the order's update time in New York time. It
        reports suspended, expired and cancel_rejected events as canceled, and
        has a zero quantity unless the event is a fill.

        Parameters
        ----------
        trade_dict: TradeUpdate
            The trade update from the Alpaca stream.

        Returns
        -------
        Return None for a new-order event.
        """
        event = _enum_value(trade_dict.event)
        if event == "new":
            return None

        order = trade_dict.order
        symbol = (order.symbol or "").lower().replace("/", "")
        return Trade(
            order_id=str(order.id),
            symbol=symbol,
            event=_TRADE_EVENTS.get(event, Order.EventType.other),
            filled_qty=(
                float(trade_dict.qty or 0.0)
                if event in ["fill", "partial_fill"]
                else 0.0
            ),
            trade_fee=0.0,
            filled_avg_price=float(order.filled_avg_price or 0.0),
            liquidity="",
            updated_at=alpaca_time(order.updated_at),
            side=Order.FillSide[_enum_value(order.side)],
        )

    @classmethod
    async def trade_update_handler(cls, data: TradeUpdate):
        """Forward an Alpaca trade update to every consumer queue.

        Send a trade_update message with the symbol and Trade fields, ignoring
        updates that yield no Trade.

        Parameters
        ----------
        data: TradeUpdate
            The trade update from the Alpaca stream.

        Raises
        ------
        Re-raise queue.Full if a queue is still full after
        _QUEUE_PUT_ATTEMPTS tries, sleeping _QUEUE_FULL_RETRY_SECONDS between
        tries; log and suppress any other exception.
        """
        try:
            # cls.get_instance().queues[symbol].put(
            #    data.__dict__["_raw"], timeout=1
            # )
            trade = cls._trade_from_dict(data)
            if not trade:
                return

            to_send = {
                "EV": QueueMessageType.TRADE_UPDATE,
                "symbol": trade.symbol,
                "trade": trade.__dict__,
            }
            for q in cls.get_instance().queues.get_allqueues():
                for attempt in range(1, _QUEUE_PUT_ATTEMPTS + 1):
                    try:
                        q.put(to_send, timeout=1)
                        break
                    except queue.Full as f:
                        if attempt == _QUEUE_PUT_ATTEMPTS:
                            raise
                        logger.error(
                            "process_message(): queue for %s is FULL:%s, sleeping for %s seconds and re-trying.",
                            data.order.symbol,
                            f,
                            _QUEUE_FULL_RETRY_SECONDS,
                        )
                        await asyncio.sleep(_QUEUE_FULL_RETRY_SECONDS)

        except queue.Full as f:
            logger.error(
                "process_message(): queue for %s is still FULL after %s attempts:%s",
                data.order.symbol,
                _QUEUE_PUT_ATTEMPTS,
                f,
            )
            raise
        # except AssertionError:
        #    for q in cls.get_instance().queues.get_allqueues():
        #        q.put(data.__dict__["_raw"], timeout=1)
        except Exception as e:
            logger.error(
                "process_message(): exception %s",
                e,
                exc_info=cls.get_instance().config.debug_enabled,
            )
