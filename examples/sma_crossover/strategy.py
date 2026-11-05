"""A momentum strategy that trades crossovers of a fast and a slow SMA.

When the fast simple moving average of the close rises above the slow one, a
bullish crossover, the price has upward momentum; when it falls back below, a
bearish crossover, the momentum has faded. SmaCrossover fires on the bars
where either happens, and SmaCrossoverRule holds a long position from a
bullish crossover to the next bearish one. sma_cross_long.toml in this
folder makes them a strategy with the watchlist filter in filter.py.

Classes
-------
SimpleMovingAverage
    Indicator of the simple moving average of the closing price.
SmaCrossover
    Signal that fires when a fast SMA crosses a slow SMA.
SmaCrossoverRule
    Rule that is long from a bullish crossover to a bearish one.
"""

import logging
import math

import pandas as pd

from liualgotrader.common.types import Order, Trade
from liualgotrader.strategy.new_base import (Indicator, OrderRequest, Signal,
                                             SymbolRule)

logger = logging.getLogger(__name__)


class SimpleMovingAverage(Indicator):
    """Indicator of the simple moving average of the closing price.

    Create instances with SimpleMovingAverage.create(ctx, ...), so that the
    signals that use the same settings share one instance.

    Attributes
    ----------
    window: int
        The number of bars to average.
    lookback_days: int
        The number of calendar days of bars to read.
    """

    def __init__(self, window: int = 20, lookback_days: int = 60, **kwargs):
        """Initialize the indicator.

        Parameters
        ----------
        window: int, default 20
            The number of bars to average.
        lookback_days: int, default 60
            The number of calendar days of bars to read, which must cover
            window bars.
        """
        super().__init__(**kwargs)
        self.window = window
        self.lookback_days = lookback_days

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        """Return the moving average of a symbol through a time.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return a DataFrame with an sma column, NaN until window bars are
        available.
        """
        start = now.normalize() - pd.Timedelta(days=self.lookback_days)
        bars = self.ctx.bars(symbol, start, now)
        return pd.DataFrame({"sma": bars["close"].rolling(self.window).mean()})


class SmaCrossover(Signal):
    """Signal that fires when a fast SMA crosses a slow SMA.

    The value is 1.0 on the bar where the fast SMA rises above the slow one,
    -1.0 on the bar where it falls below, and NaN on the other bars.

    Attributes
    ----------
    fast: SimpleMovingAverage
        The shared fast moving average.
    slow: SimpleMovingAverage
        The shared slow moving average.
    """

    def __init__(
        self,
        fast: int = 10,
        slow: int = 30,
        lookback_days: int = 60,
        **kwargs,
    ):
        """Initialize the signal and create its indicators.

        Parameters
        ----------
        fast: int, default 10
            The number of bars of the fast moving average.
        slow: int, default 30
            The number of bars of the slow moving average.
        lookback_days: int, default 60
            The number of calendar days of bars to read, which must cover
            slow bars.

        Raises
        ------
        Raise ValueError unless 0 < fast < slow.
        """
        super().__init__(**kwargs)
        if not 0 < fast < slow:
            raise ValueError(f"need 0 < fast < slow, got {fast} and {slow}")
        self.fast = SimpleMovingAverage.create(
            self.ctx, window=fast, lookback_days=lookback_days
        )
        self.slow = SimpleMovingAverage.create(
            self.ctx, window=slow, lookback_days=lookback_days
        )

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        """Return the crossovers of a symbol through a time.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return 1.0 for bullish crossovers, -1.0 for bearish ones and NaN for
        the other bars, including those before both averages have values.
        """
        spread = (
            self.fast.get(symbol, now).sma - self.slow.get(symbol, now).sma
        )
        previous = spread.shift()
        values = pd.Series(math.nan, index=spread.index)
        values[(previous <= 0) & (spread > 0)] = 1.0
        values[(previous >= 0) & (spread < 0)] = -1.0
        return values


class SmaCrossoverRule(SymbolRule):
    """Rule that is long from a bullish crossover to a bearish one.

    Buy qty at market when flat and the rule's signal fires bullish, and
    sell the whole position at market when it fires bearish. The runtime
    asks the rule on every bar while it holds a position, but the rule acts
    only on crossovers.

    Attributes
    ----------
    qty: float
        The quantity to buy on a bullish crossover.
    """

    def __init__(self, qty: float = 10, **kwargs):
        """Initialize the rule.

        Parameters
        ----------
        qty: float, default 10
            The quantity to buy on a bullish crossover.

        Raises
        ------
        Raise ValueError if qty is not positive.
        """
        super().__init__(**kwargs)
        if qty <= 0:
            raise ValueError(f"qty must be positive, got {qty}")
        self.qty = qty

    async def decide(
        self, symbol: str, now: pd.Timestamp, position: float
    ) -> list[OrderRequest]:
        """Return a buy on a bullish crossover and a sell on a bearish one.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        position: float
            The strategy's position in symbol.
        """
        # NaN, which no comparison holds for, unless the signal fired
        value = self.signal.at(symbol, now)
        if not position and value > 0:
            logger.info("%s: bullish crossover of %s at %s", self, symbol, now)
            return [OrderRequest(symbol, Order.FillSide.buy, self.qty)]
        if position > 0 and value < 0:
            logger.info("%s: bearish crossover of %s at %s", self, symbol, now)
            return [OrderRequest(symbol, Order.FillSide.sell, position)]
        return []

    async def on_fill(self, trade: Trade) -> None:
        """Log a fill of one of the rule's orders.

        Parameters
        ----------
        trade: Trade
            The execution.
        """
        logger.info(
            "%s: %s %s %s at %s",
            self,
            trade.side.name,
            trade.filled_qty,
            trade.symbol,
            trade.filled_avg_price,
        )

    async def on_cancel(self, order: Order) -> None:
        """Log one of the rule's orders ending without a full fill.

        Parameters
        ----------
        order: Order
            The order, with its final status.
        """
        logger.info(
            "%s: order %s for %s ended %s",
            self,
            order.order_id,
            order.symbol,
            order.event.name,
        )
