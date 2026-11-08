"""Backtest the SMA crossover example on synthetic daily bars.

The bars stand in for a DataLoader, so the test needs no credentials.
"""

import pandas as pd
import pytest

from liualgotrader.common import clock
from liualgotrader.common.types import TimeScale
from liualgotrader.enhanced_backtest import Backtest
from liualgotrader.strategy.new_base import Context
from liualgotrader.strategy.runtime import RunState
from liualgotrader.strategy.tradeplan import create_strategies, load_tradeplan

DAY = pd.Timedelta(days=1)


class Bars:
    """The loaded bars of a symbol, sliced like those of a DataLoader."""

    def __init__(self, symbol_data: pd.DataFrame):
        self.symbol_data = symbol_data

    def __getitem__(self, key):
        return self.symbol_data[key]


def daily_bars(closes: list[float]) -> pd.DataFrame:
    """Return daily bars at midnight, opening at the previous close."""
    index = pd.date_range(
        pd.Timestamp("2026-01-01", tz=clock.NY), periods=len(closes), freq="D"
    )
    close = pd.Series(closes, index=index)
    return pd.DataFrame(
        {
            "open": close.shift(fill_value=closes[0]),
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        }
    )


@pytest.mark.asyncio
async def test_buys_bullish_and_sells_bearish_crossover() -> None:
    # down for 40 days, up for 40, then down for 40
    closes = (
        [100.0 - i for i in range(40)]
        + [61.0 + 2 * i for i in range(40)]
        + [139.0 - 2 * i for i in range(40)]
    )
    bars = daily_bars(closes)
    [spec] = load_tradeplan("./examples/sma_crossover")
    spec["filter"]["symbols"] = ["AAPL"]
    ctx = Context({"aapl": Bars(bars)}, backtesting=True)
    session = Backtest(
        ctx, RunState(create_strategies([spec], ctx)), TimeScale.day
    )

    for day in bars.index:
        await session.simulate_day(day, day + DAY - pd.Timedelta(seconds=1))

    trades = pd.DataFrame(session.trades)
    if list(trades.side) != ["buy", "sell"]:
        raise AssertionError(f"unexpected trades {trades}")

    fast = bars.close.rolling(10).mean()
    slow = bars.close.rolling(30).mean()
    above = fast > slow
    bullish = above[above & ~above.shift(fill_value=True)].index[0]
    bearish = above[~above & above.shift(fill_value=False)].index[0]
    # each order fills at the open of the bar after its crossover
    if list(trades.time) != [bullish + DAY, bearish + DAY]:
        raise AssertionError(
            f"fills at {list(trades.time)}, crossovers at {bullish} and "
            f"{bearish}"
        )
    if list(trades.price) != [
        bars.open[bullish + DAY],
        bars.open[bearish + DAY],
    ]:
        raise AssertionError(f"unexpected prices {list(trades.price)}")
    if session.state.strategies["sma_cross_long"].positions:
        raise AssertionError("position left open after the bearish crossover")
