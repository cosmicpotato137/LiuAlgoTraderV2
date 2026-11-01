"""A long momentum day-trading strategy, as indicators, a signal and a rule.

MomentumSignal fires when a symbol breaks out above its high of the first
minutes of the session, with MACD confirming the trend. MomentumLongRule buys
on the signal unless RSI says the symbol is overbought, sizes the position by
its risk to a stop under the latest local minimum, and sells at the stop, at
the target, when momentum fades or to scale out of a gain.

Classes
-------
Macd
    Indicator of the MACD of the closing prices during market hours.
Rsi
    Indicator of the RSI of the closing prices during market hours.
MomentumSignal
    Signal that fires on a breakout above the opening range high.
MomentumLongRule
    Rule that buys momentum breakouts and manages their exits.

Functions
---------
macd
    Return the MACD line, signal line and histogram of a price series.
rsi
    Return the relative strength index of a price series.
"""

import logging
from typing import Optional

import pandas as pd

from liualgotrader.common import clock
from liualgotrader.common.types import Order, OrderType, Trade
from liualgotrader.fincalcs.support_resistance import find_stop
from liualgotrader.strategy.new_base import (Indicator, OrderRequest, Signal,
                                             SymbolRule, lookback_start)

logger = logging.getLogger(__name__)


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """Return the MACD line, signal line and histogram of a price series.

    Use the exponential moving averages of stockstats.

    Parameters
    ----------
    close: pd.Series
        The prices.
    fast: int
        The span of the fast moving average.
    slow: int
        The span of the slow moving average.
    signal: int
        The span of the moving average of the MACD line.

    Returns
    -------
    Return a DataFrame with macd, macds and macdh columns.
    """
    line = (
        close.ewm(span=fast, min_periods=1).mean()
        - close.ewm(span=slow, min_periods=1).mean()
    )
    signal_line = line.ewm(span=signal, min_periods=1).mean()
    return pd.DataFrame(
        {"macd": line, "macds": signal_line, "macdh": line - signal_line}
    )


def rsi(close: pd.Series, window: int) -> pd.Series:
    """Return the relative strength index of a price series.

    Use the smoothed moving averages of stockstats, where the first value,
    and any value with no price change in its window, is 50.

    Parameters
    ----------
    close: pd.Series
        The prices.
    window: int
        The smoothing window.
    """
    diff = close.diff().fillna(0.0)
    up = diff.clip(lower=0.0).ewm(alpha=1.0 / window).mean()
    down = (-diff).clip(lower=0.0).ewm(alpha=1.0 / window).mean()
    total = up + down
    values = (100 * up / total).where(total != 0, 50.0)
    if len(values):
        values.iloc[0] = 50.0
    return values


def _market_hours_close(bars: pd.DataFrame) -> pd.Series:
    """Return the closing prices of the bars of the regular session."""
    return bars["close"].dropna().between_time("9:30", "16:00")


def _vwap(bar: pd.Series) -> float:
    """Return the vwap of a bar, or 0.0 if the bar has none.

    The streamed bars of some data providers have a NaN vwap.
    """
    return 0.0 if pd.isna(bar.vwap) else float(bar.vwap)


class Macd(Indicator):
    """Indicator of the MACD of the closing prices during market hours.

    Attributes
    ----------
    fast: int
        The span of the fast moving average.
    slow: int
        The span of the slow moving average.
    signal: int
        The span of the moving average of the MACD line.
    lookback_days: int
        The number of calendar days of bars to read.
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        lookback_days: int = 5,
        **kwargs,
    ):
        """Initialize the indicator.

        Parameters
        ----------
        fast: int, default 12
            The span of the fast moving average.
        slow: int, default 26
            The span of the slow moving average.
        signal: int, default 9
            The span of the moving average of the MACD line.
        lookback_days: int, default 5
            The number of calendar days of bars to read.
        """
        super().__init__(**kwargs)
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.lookback_days = lookback_days

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        """Return the MACD of a symbol through a time.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return a DataFrame with macd, macds and macdh columns and a row per
        bar of the regular session.
        """
        bars = self.ctx.bars(
            symbol, lookback_start(now, self.lookback_days), now
        )
        return macd(
            _market_hours_close(bars), self.fast, self.slow, self.signal
        )


class Rsi(Indicator):
    """Indicator of the RSI of the closing prices during market hours.

    Attributes
    ----------
    window: int
        The smoothing window.
    lookback_days: int
        The number of calendar days of bars to read.
    """

    def __init__(self, window: int = 20, lookback_days: int = 5, **kwargs):
        """Initialize the indicator.

        Parameters
        ----------
        window: int, default 20
            The smoothing window.
        lookback_days: int, default 5
            The number of calendar days of bars to read.
        """
        super().__init__(**kwargs)
        self.window = window
        self.lookback_days = lookback_days

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        """Return the RSI of a symbol through a time.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.

        Returns
        -------
        Return a DataFrame with an rsi column and a row per bar of the
        regular session.
        """
        bars = self.ctx.bars(
            symbol, lookback_start(now, self.lookback_days), now
        )
        return rsi(_market_hours_close(bars), self.window).to_frame("rsi")


class MomentumSignal(Signal):
    """Signal that fires on a breakout above the opening range high.

    A bar fires, with the value 1.0, when it closes above the highest price
    since the market opened, up to breakout_minutes after the open, and:

    - the MACD line is positive, rising for the last three bars and more than
      10% above its signal line, with a rising histogram;
    - the bar opens above the previous close, and its vwap is above its open,
      or, for a bar without a vwap, its close is.

    Attributes
    ----------
    breakout_minutes: int
        The length of the opening range, in minutes.
    lookback_days: int
        The number of calendar days of bars to read.
    macd: Macd
        The shared MACD indicator.
    """

    def __init__(
        self, breakout_minutes: int = 15, lookback_days: int = 5, **kwargs
    ):
        """Initialize the signal and create its indicator.

        Parameters
        ----------
        breakout_minutes: int, default 15
            The length of the opening range, in minutes.
        lookback_days: int, default 5
            The number of calendar days of bars to read.
        """
        super().__init__(**kwargs)
        self.breakout_minutes = breakout_minutes
        self.lookback_days = lookback_days
        self.macd = Macd.create(self.ctx, lookback_days=lookback_days)

    def _opening_range_high(self, bars: pd.DataFrame) -> pd.Series:
        """Return the opening range high known at each bar.

        Within the opening range, the high so far includes the bar itself,
        so a bar can only break out after the range ends. Before the market
        opens, the high is NaN.

        Parameters
        ----------
        bars: pd.DataFrame
            The bars, of one or more days.
        """
        highs = []
        for day, day_bars in bars.groupby(bars.index.date):
            market_open = clock.market_open(day)
            opening_range = day_bars.loc[
                market_open : market_open
                + pd.Timedelta(minutes=self.breakout_minutes)
            ]
            highs.append(
                opening_range["high"]
                .cummax()
                .reindex(day_bars.index, method="ffill")
            )
        if not highs:
            return pd.Series(float("nan"), index=bars.index)
        return pd.concat(highs).reindex(bars.index)

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        """Return 1.0 for the bars that break out, and NaN for the others.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the last row to compute.
        """
        bars = self.ctx.bars(
            symbol, lookback_start(now, self.lookback_days), now
        )
        if bars.empty:
            return pd.Series(dtype=float)

        m = self.macd.get(symbol, now)
        rising = (m.macd.diff() > 0) & (m.macd.shift().diff() > 0)
        hist_rising = (m.macdh.diff() > 0) & (m.macdh.shift().diff() > 0)
        trend = (
            (m.macd > 0) & rising & (m.macd > m.macds * 1.1) & hist_rising
        ).reindex(bars.index, fill_value=False)

        vwap = bars.vwap.fillna(0.0)
        prev_close = bars.close.shift()
        price_ok = (vwap != 0.0) & (vwap > bars.open) | (vwap == 0.0) & (
            bars.close > bars.open
        )
        breakout = bars.close > self._opening_range_high(bars)

        fires = breakout & trend & price_ok & (bars.open > prev_close)
        return pd.Series(1.0, index=bars.index).where(fires)


class MomentumLongRule(SymbolRule):
    """Rule that buys momentum breakouts and manages their exits.

    On a signal, buy unless RSI is at least rsi_limit, which starts a cool
    down instead. Size the position so that a fall to the stop, the latest
    local minimum, loses risk times portfolio_value. Set the target at three
    times that risk above the close. Buy at market in the morning rush, and at
    a limit of the higher of the close and vwap later.

    Sell the whole position at the stop, when the close is below the cost and
    momentum turns negative, at the target once MACD turns negative, when RSI
    is too high (which also starts a cool down), or when MACD turns down after
    a gain. Sell half at a limit to scale out of a 4% gain. After a 1% drop
    below cost, the position is whipsawed, and sells at a limit once it
    recovers above cost and MACD turns down.

    Attributes
    ----------
    portfolio_value: float
        The portfolio value that positions are sized from.
    risk: float
        The fraction of portfolio_value to risk per position.
    rsi_limit: float
        The RSI at or above which not to buy.
    cool_down_minutes: int
        How long not to buy after RSI is too high.
    morning_rush_minutes: int
        How long after the open to buy at market.
    lookback_days: int
        The number of calendar days of bars to read.
    cost_basis: dict[str, float]
        The buy price of each position.
    scalp_basis: dict[str, float]
        The price of the latest fill of each position.
    target_prices: dict[str, float]
        The target price of each position.
    stop_prices: dict[str, float]
        The stop price of each position.
    whipsawed: dict[str, bool]
        Whether each position dropped 1% below its cost.
    cool_down: dict[str, pd.Timestamp]
        The time until which not to buy each symbol.
    """

    def __init__(
        self,
        portfolio_value: float = 25000.0,
        risk: float = 0.001,
        rsi_limit: float = 75,
        cool_down_minutes: int = 5,
        morning_rush_minutes: int = 30,
        lookback_days: int = 5,
        **kwargs,
    ):
        """Initialize the rule.

        Parameters
        ----------
        portfolio_value: float, default 25000.0
            The portfolio value that positions are sized from.
        risk: float, default 0.001
            The fraction of portfolio_value to risk per position.
        rsi_limit: float, default 75
            The RSI at or above which not to buy.
        cool_down_minutes: int, default 5
            How long not to buy after RSI is too high.
        morning_rush_minutes: int, default 30
            How long after the open to buy at market.
        lookback_days: int, default 5
            The number of calendar days of bars to read.
        """
        super().__init__(**kwargs)
        self.portfolio_value = portfolio_value
        self.risk = risk
        self.rsi_limit = rsi_limit
        self.cool_down_minutes = cool_down_minutes
        self.morning_rush_minutes = morning_rush_minutes
        self.lookback_days = lookback_days
        self.rsi = Rsi.create(self.ctx, lookback_days=lookback_days)
        self.cost_basis: dict[str, float] = {}
        self.scalp_basis: dict[str, float] = {}
        self.target_prices: dict[str, float] = {}
        self.stop_prices: dict[str, float] = {}
        self.whipsawed: dict[str, bool] = {}
        self.cool_down: dict[str, pd.Timestamp] = {}

    def _start_cool_down(self, symbol: str, now: pd.Timestamp) -> None:
        """Keep the rule from buying symbol for cool_down_minutes."""
        self.cool_down[symbol] = now.floor("min") + pd.Timedelta(
            minutes=self.cool_down_minutes
        )

    async def decide(
        self,
        symbol: str,
        now: pd.Timestamp,
        position: float,
        fired: dict[str, float],
    ) -> list[OrderRequest]:
        """Return an entry when flat and a signal fired, or an exit.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        position: float
            The rule's position in symbol.
        fired: dict[str, float]
            The value of each of the rule's signals that fired at now.
        """
        bars = self.ctx.bars(
            symbol, lookback_start(now, self.lookback_days), now
        )
        if bars.empty:
            return []

        morning_rush = now - clock.market_open(now.date()) < pd.Timedelta(
            minutes=self.morning_rush_minutes
        )
        if not position:
            cooling_down = (
                symbol in self.cool_down
                and now.floor("min") <= self.cool_down[symbol]
            )
            if fired and not cooling_down:
                return self._enter(symbol, now, bars, morning_rush)
        elif position > 0 and symbol in self.cost_basis:
            return self._exit(symbol, now, position, bars, morning_rush)
        return []

    def _enter(
        self,
        symbol: str,
        now: pd.Timestamp,
        bars: pd.DataFrame,
        morning_rush: bool,
    ) -> list[OrderRequest]:
        """Return the buy order for a breakout, if RSI and the stop allow.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        bars: pd.DataFrame
            The bars of symbol through now.
        morning_rush: bool
            Whether to buy at market.
        """
        latest_rsi = self.rsi.get(symbol, now).rsi
        if latest_rsi.empty or latest_rsi.iloc[-1] >= self.rsi_limit:
            logger.info(
                "[%s][%s] %s RSI over-bought, cool down for %s min",
                self,
                now,
                symbol,
                self.cool_down_minutes,
            )
            self._start_cool_down(symbol, now)
            return []

        data = bars.iloc[-1]
        stop_price: Optional[float] = find_stop(
            _vwap(data) or data.close, bars, now
        )
        if stop_price is None:
            logger.info("[%s][%s] %s has no stop", self, now, symbol)
            return []

        qty = float(
            self.portfolio_value * self.risk // (data.close - stop_price)
        )
        if not qty:
            qty = 1
        if qty <= 0:
            return []

        self.stop_prices[symbol] = stop_price
        self.target_prices[symbol] = 3 * (data.close - stop_price) + data.close
        self.whipsawed[symbol] = False
        buy_price = max(data.close, _vwap(data))
        logger.info(
            "[%s][%s] buying %s shares of %s at %s target %s stop %s",
            self,
            now,
            qty,
            symbol,
            "market" if morning_rush else buy_price,
            self.target_prices[symbol],
            stop_price,
        )
        return [
            (
                OrderRequest(symbol, Order.FillSide.buy, qty)
                if morning_rush
                else OrderRequest(
                    symbol,
                    Order.FillSide.buy,
                    qty,
                    OrderType.LIMIT,
                    float(buy_price),
                )
            )
        ]

    def _exit(
        self,
        symbol: str,
        now: pd.Timestamp,
        position: float,
        bars: pd.DataFrame,
        morning_rush: bool,
    ) -> list[OrderRequest]:
        """Return the sell order for a position, if an exit applies.

        Parameters
        ----------
        symbol: str
            The symbol.
        now: pd.Timestamp
            The time of the latest bar.
        position: float
            The rule's position in symbol, which is positive.
        bars: pd.DataFrame
            The bars of symbol through now.
        morning_rush: bool
            Whether the morning rush, with its higher RSI limit, is on.
        """
        data = bars.iloc[-1]
        vwap = _vwap(data)
        cost_basis = self.cost_basis[symbol]
        scalp_basis = self.scalp_basis[symbol]
        if not self.whipsawed.get(symbol) and data.close < cost_basis * 0.99:
            self.whipsawed[symbol] = True

        # momentum of the session so far, with the latest price at vwap
        close = _market_hours_close(bars)
        if vwap and len(close):
            close.iloc[-1] = vwap
        m = macd(close, fast=13, slow=21, signal=9)
        sell_rsi = rsi(close, 20)
        if len(m) < 2:
            return []

        macd_val = m.macd.iloc[-1]
        macd_signal_val = m.macds.iloc[-1]
        round_factor = 2 if macd_val >= 0.1 or macd_signal_val >= 0.1 else 3
        macd_below_signal = round(macd_val, round_factor) < round(
            macd_signal_val, round_factor
        )
        macd_turning_down = round(macd_val, round_factor) < round(
            m.macd.iloc[-2], round_factor
        )
        movement = (data.close - scalp_basis) / scalp_basis
        scalp_threshold = (self.target_prices[symbol] + scalp_basis) / 2.0

        reason = None
        qty, order_type = position, OrderType.MARKET
        if data.close <= self.stop_prices[symbol]:
            reason = "stopped"
        elif (
            vwap
            and vwap < cost_basis
            and round(macd_val, 2) < 0
            and sell_rsi.iloc[-1] < sell_rsi.iloc[-2]
            and macd_turning_down
            and vwap < 0.95 * data.average
        ):
            reason = (
                "below cost & macd negative & RSI trending down and too far "
                "from VWAP"
            )
        elif data.close >= self.target_prices[symbol] and macd_val <= 0:
            reason = "above target & macd negative"
        elif sell_rsi.iloc[-1] >= (85 if morning_rush else 79):
            reason = "rsi max, cool-down"
            self._start_cool_down(symbol, now)
        elif (
            (scalp_basis > cost_basis or movement > 0.02)
            and macd_below_signal
            and macd_turning_down
        ):
            reason = "bail"
        elif movement > 0.04 or vwap > scalp_threshold:
            reason = "scale-out"
            qty = int(position / 2) if position > 1 else 1
            order_type = OrderType.LIMIT
        elif (
            self.whipsawed.get(symbol)
            and data.close > cost_basis
            and macd_below_signal
            and macd_turning_down
        ):
            reason = "bail post whipsawed"
            order_type = OrderType.LIMIT

        if reason is None:
            return []

        logger.info(
            "[%s][%s] selling %s shares of %s at %s with reason: %s",
            self,
            now,
            qty,
            symbol,
            data.close if order_type == OrderType.LIMIT else "market",
            reason,
        )
        return [
            OrderRequest(
                symbol,
                Order.FillSide.sell,
                qty,
                order_type,
                (float(data.close) if order_type == OrderType.LIMIT else None),
            )
        ]

    async def on_fill(self, trade: Trade) -> None:
        """Record the price of a fill as the cost or scalp basis.

        Parameters
        ----------
        trade: Trade
            The execution.
        """
        if trade.side == Order.FillSide.buy:
            self.cost_basis[trade.symbol] = trade.filled_avg_price
        self.scalp_basis[trade.symbol] = trade.filled_avg_price
