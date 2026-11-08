from unittest.mock import MagicMock

import pandas as pd
import pytest

from liualgotrader.common.types import Order
from liualgotrader.vendors.gemini import trader as gemini_trader_module
from liualgotrader.vendors.gemini.config import GeminiConfig
from liualgotrader.vendors.gemini.trader import GeminiTrader


def _order() -> Order:
    return Order(
        order_id="12345",
        symbol="btcusd",
        event=Order.EventType.open,
        submitted_at=pd.Timestamp("2026-11-02 10:00", tz="America/New_York"),
    )


@pytest.fixture
def gemini_trader(monkeypatch) -> GeminiTrader:
    trader = GeminiTrader(GeminiConfig())
    monkeypatch.setattr(trader, "_generate_request_headers", lambda _: {})
    return trader


@pytest.mark.parametrize("is_cancelled", [True, False])
async def test_cancel_order_returns_bool(
    gemini_trader, monkeypatch, is_cancelled
):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "order_id": "12345",
        "is_live": False,
        "is_cancelled": is_cancelled,
    }
    monkeypatch.setattr(
        gemini_trader_module.requests, "post", lambda *_, **__: response
    )

    assert await gemini_trader.cancel_order(_order()) is is_cancelled


async def test_cancel_order_error_raises(gemini_trader, monkeypatch):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "result": "error",
        "reason": "OrderNotFound",
        "message": "Order 12345 not found",
    }
    monkeypatch.setattr(
        gemini_trader_module.requests, "post", lambda *_, **__: response
    )

    with pytest.raises(AssertionError):
        await gemini_trader.cancel_order(_order())
