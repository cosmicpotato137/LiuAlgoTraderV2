import pytest

from liualgotrader.strategy.new_base import Context


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


@pytest.mark.asyncio
async def test_asks_trader_once_per_symbol() -> None:
    trader = FakeTrader({"aapl": True, "gme": False})
    ctx = Context(None, trader=trader)
    for _ in range(3):
        if not await ctx.is_shortable("aapl"):
            raise AssertionError("aapl should be shortable")
        if await ctx.is_shortable("gme"):
            raise AssertionError("gme should not be shortable")
    if trader.calls != ["aapl", "gme"]:
        raise AssertionError(f"unexpected lookups: {trader.calls}")


@pytest.mark.asyncio
async def test_failed_lookup_is_not_shortable() -> None:
    trader = FakeTrader({"aapl": ConnectionError("down")})
    ctx = Context(None, trader=trader)
    if await ctx.is_shortable("aapl"):
        raise AssertionError("a failed lookup should not be shortable")
    await ctx.is_shortable("aapl")
    if trader.calls != ["aapl"]:
        raise AssertionError(f"failed lookup retried: {trader.calls}")


@pytest.mark.asyncio
async def test_backtest_and_missing_trader() -> None:
    trader = FakeTrader({})
    if not await Context(None, trader, backtesting=True).is_shortable("aapl"):
        raise AssertionError("backtests should treat symbols as shortable")
    if trader.calls:
        raise AssertionError("backtest asked the broker")
    if await Context(None).is_shortable("aapl"):
        raise AssertionError("no trader should mean not shortable")
