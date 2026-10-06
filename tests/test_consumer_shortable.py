import pytest

from liualgotrader import consumer


class FakeTrader:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def is_shortable(self, symbol: str) -> bool:
        self.calls.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def clear_cache():
    consumer.shortable.clear()
    yield
    consumer.shortable.clear()


@pytest.mark.asyncio
async def test_asks_trader_once_per_symbol() -> None:
    trader = FakeTrader({"aapl": True, "gme": False})
    for _ in range(3):
        if not await consumer.is_shortable(trader, "aapl"):
            raise AssertionError("aapl should be shortable")
        if await consumer.is_shortable(trader, "gme"):
            raise AssertionError("gme should not be shortable")
    if trader.calls != ["aapl", "gme"]:
        raise AssertionError(f"unexpected lookups: {trader.calls}")


@pytest.mark.asyncio
async def test_failed_lookup_is_not_shortable() -> None:
    trader = FakeTrader({"aapl": ConnectionError("down")})
    if await consumer.is_shortable(trader, "aapl"):
        raise AssertionError("a failed lookup should not be shortable")
    await consumer.is_shortable(trader, "aapl")
    if trader.calls != ["aapl"]:
        raise AssertionError(f"failed lookup retried: {trader.calls}")
