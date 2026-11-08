from unittest.mock import MagicMock

import pytest
from alpaca.common.exceptions import APIError

from liualgotrader.vendors.alpaca import data as alpaca_data
from liualgotrader.vendors.alpaca import trader as alpaca_trader
from liualgotrader.vendors.alpaca.config import AlpacaConfig
from liualgotrader.vendors.gemini import data as gemini_data
from liualgotrader.vendors.gemini.config import GeminiConfig
from liualgotrader.vendors.tradier import data as tradier_data
from liualgotrader.vendors.tradier import trader as tradier_trader
from liualgotrader.vendors.tradier.config import TradierConfig


class _Responses:
    """Return a response with each status code in turn, then the last one."""

    def __init__(self, *status_codes: int):
        self.status_codes = list(status_codes)
        self.calls = 0

    def __call__(self, *args, **kwargs):
        code = self.status_codes[min(self.calls, len(self.status_codes) - 1)]
        self.calls += 1
        return MagicMock(status_code=code, headers={})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _async_sleep(_):
        pass

    monkeypatch.setattr(tradier_data.time_action, "sleep", lambda _: None)
    monkeypatch.setattr(tradier_trader.time_action, "sleep", lambda _: None)
    monkeypatch.setattr(gemini_data.time, "sleep", lambda _: None)
    monkeypatch.setattr(alpaca_data.time, "sleep", lambda _: None)
    monkeypatch.setattr(alpaca_trader.asyncio, "sleep", _async_sleep)


def test_tradier_data_retries_then_succeeds(monkeypatch):
    responses = _Responses(429, 502, 200)
    monkeypatch.setattr(tradier_data.requests, "get", responses)

    r = tradier_data.TradierData(TradierConfig())._get("https://x")

    assert r.status_code == 200
    assert responses.calls == 3


def test_tradier_data_gives_up(monkeypatch):
    responses = _Responses(429)
    monkeypatch.setattr(tradier_data.requests, "get", responses)
    config = TradierConfig(request_attempts=3)

    with pytest.raises(ValueError):
        tradier_data.TradierData(config)._get("https://x")
    assert responses.calls == 3


@pytest.mark.parametrize("verb", ["get", "post", "delete"])
def test_tradier_trader_retries_then_succeeds(monkeypatch, verb):
    responses = _Responses(502, 200)
    monkeypatch.setattr(tradier_trader.requests, verb, responses)
    trader = tradier_trader.TradierTrader(TradierConfig())

    r = getattr(trader, f"_{verb}")("https://x")

    assert r.status_code == 200
    assert responses.calls == 2


@pytest.mark.parametrize("verb", ["get", "post", "delete"])
def test_tradier_trader_gives_up(monkeypatch, verb):
    responses = _Responses(429)
    monkeypatch.setattr(tradier_trader.requests, verb, responses)
    trader = tradier_trader.TradierTrader(TradierConfig(request_attempts=3))

    with pytest.raises(ValueError):
        getattr(trader, f"_{verb}")("https://x")
    assert responses.calls == 3


def test_gemini_data_returns_last_response(monkeypatch):
    responses = _Responses(502)
    monkeypatch.setattr(gemini_data._session, "get", responses)

    r = gemini_data.requests_get("https://x", GeminiConfig(request_attempts=3))

    assert r.status_code == 502
    assert responses.calls == 3


def _api_error(status_code: int) -> APIError:
    return APIError(
        "{}", http_error=MagicMock(response=MagicMock(status_code=status_code))
    )


def test_alpaca_data_retries_then_succeeds():
    outcomes = [_api_error(500), _api_error(429), "bars"]

    def request():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert (
        alpaca_data._retry_transient_errors(AlpacaConfig(), request) == "bars"
    )


def test_alpaca_data_gives_up():
    calls = 0

    def request():
        nonlocal calls
        calls += 1
        raise _api_error(504)

    with pytest.raises(APIError):
        alpaca_data._retry_transient_errors(
            AlpacaConfig(request_attempts=3), request
        )
    assert calls == 3


def test_alpaca_data_does_not_retry_other_errors():
    calls = 0

    def request():
        nonlocal calls
        calls += 1
        raise _api_error(403)

    with pytest.raises(APIError):
        alpaca_data._retry_transient_errors(AlpacaConfig(), request)
    assert calls == 1


async def test_alpaca_brokerage_retries_then_succeeds():
    responses = _Responses(429, 504, 200)

    r = await alpaca_trader._send_brokerage_request(AlpacaConfig(), responses)

    assert r.status_code == 200
    assert responses.calls == 3


async def test_alpaca_brokerage_gives_up():
    responses = _Responses(429)

    r = await alpaca_trader._send_brokerage_request(
        AlpacaConfig(request_attempts=3), responses
    )

    assert r.status_code == 429
    assert responses.calls == 3


async def test_alpaca_brokerage_waits_retry_seconds(monkeypatch):
    waits = []

    async def _sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(alpaca_trader.asyncio, "sleep", _sleep)
    responses = _Responses(504, 200)

    await alpaca_trader._send_brokerage_request(
        AlpacaConfig(request_retry_seconds=2.5), responses
    )

    assert waits == [2.5]
