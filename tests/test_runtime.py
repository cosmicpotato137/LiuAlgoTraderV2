"""Tests of the run state, the backtester and the producer's symbol routing.

The components here read synthetic bars, so the tests need no credentials.
"""

import asyncio
import json
import math
import queue
from datetime import date

import pandas as pd
import pytest

from liualgotrader import filters_runner, producer
from liualgotrader.common import clock
from liualgotrader.common.exceptions import OwnershipCollision
from liualgotrader.common.types import (
    AssetType,
    Order,
    OrderType,
    QueueMessageType,
    SymbolQueueMap,
    TimeScale,
    Trade,
)
from liualgotrader.consumer import Consumer
from liualgotrader.enhanced_backtest import (
    Backtest,
    net_cash_flow,
    write_results,
)
from liualgotrader.market_calendar.base import CryptoCalendar
from liualgotrader.strategy import base
from liualgotrader.strategy.base import (
    Context,
    Filter,
    OpenOrder,
    OrderRequest,
    PortfolioRule,
    Signal,
    Strategy,
    SymbolRule,
)
from liualgotrader.strategy.runtime import RunState
from liualgotrader.strategy.tradeplan import portfolio_strategy_names

DAY_START = pd.Timestamp("2026-10-01 09:30", tz=clock.NY)
MINUTE = pd.Timedelta(minutes=1)
BUY, SELL = Order.FillSide.buy, Order.FillSide.sell


def make_bars(opens, lows=None, highs=None) -> pd.DataFrame:
    """Return minute bars from DAY_START with the given opens."""
    index = pd.date_range(DAY_START, periods=len(opens), freq="1min")
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs or [o + 1.0 for o in opens],
            "low": lows or [o - 1.0 for o in opens],
            "close": opens,
            "volume": [100] * len(opens),
        },
        index=index,
    )


class Bars:
    """The loaded bars of a symbol, sliced like those of a DataLoader."""

    def __init__(self, symbol_data: pd.DataFrame):
        self.symbol_data = symbol_data

    def __getitem__(self, key):
        return self.symbol_data[key]


def loader(**bars: pd.DataFrame) -> dict:
    """Return a stand-in for a DataLoader that holds the given bars."""
    return {symbol: Bars(data) for symbol, data in bars.items()}


class Fixed(Filter):
    """Select a fixed list of symbols."""

    def __init__(self, symbols=("aapl",), **kwargs):
        super().__init__(**kwargs)
        self.symbols = list(symbols)

    async def run(self, now):
        return self.symbols


class Always(Signal):
    """Fire +1 on every bar."""

    def compute(self, symbol, now):
        bars = self.ctx.bars(symbol, DAY_START, now)
        return pd.Series(1.0, index=bars.index)


class Recorder(SymbolRule):
    """Buy when flat and fired, then sell the position on the next call.

    Record each call with the value of the signal.
    """

    def __init__(self, qty=1.0, limit_price=None, **kwargs):
        super().__init__(**kwargs)
        self.qty = qty
        self.limit_price = limit_price
        self.calls = []
        self.fills = []
        self.cancels = []

    async def decide(self, symbol, now, position):
        value = self.signal.at(symbol, now)
        self.calls.append((symbol, now, position, value))
        if position:
            return [OrderRequest(symbol, SELL, abs(position))]
        if not math.isnan(value):
            return [
                OrderRequest(
                    symbol,
                    BUY,
                    self.qty,
                    OrderType.LIMIT if self.limit_price else OrderType.MARKET,
                    self.limit_price,
                )
            ]
        return []

    async def on_fill(self, trade):
        self.fills.append(trade)

    async def on_cancel(self, order):
        self.cancels.append(order)


class Rebalance(PortfolioRule):
    """Record the signal values and buy one of each symbol with a value."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    async def decide(self, now, positions, symbols):
        values = self.signal.latest(symbols, now)
        self.calls.append((positions, values))
        return [
            OrderRequest(symbol, BUY, 1.0)
            for symbol, value in values.items()
            if value > 0
        ]


class CountingAlways(Always):
    """Fire +1 on every bar, and record the times it computes through."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.computed = []

    def compute(self, symbol, now):
        self.computed.append(now)
        return super().compute(symbol, now)


def make_strategies(
    ctx, *rule_names, portfolio=None, filters=None, signals=None
):
    """Return a strategy for each rule, by name, whose filter and signal have
    the name of the rule, as a trade plan may name them.

    The rules are Recorder rules, and a Rebalance rule named portfolio. The
    filter and the signal of a strategy are the ones of its name in filters
    and signals, or else a Fixed filter and an Always signal.
    """
    names = [*rule_names, *([portfolio] if portfolio else [])]
    filters = {
        name: (filters or {}).get(name) or Fixed(ctx=ctx, name=name)
        for name in names
    }
    signals = {
        name: (signals or {}).get(name) or Always(ctx=ctx, name=name)
        for name in names
    }

    def rule(name):
        if name == portfolio:
            return Rebalance(
                ctx=ctx, name=name, signal=signals[name], recurrence=MINUTE
            )
        return Recorder(ctx=ctx, name=name, signal=signals[name])

    return {name: Strategy(name, rule(name), filters[name]) for name in names}


def submitted(order_id: str, symbol: str, side=BUY) -> Order:
    return Order(
        order_id=order_id,
        symbol=symbol,
        event=Order.EventType.open,
        submitted_at=DAY_START,
        side=side,
    )


def fill(order_id: str, qty: float, side=BUY, partial=False) -> Trade:
    return Trade(
        order_id=order_id,
        symbol="aapl",
        event=(
            Order.EventType.partial_fill if partial else Order.EventType.fill
        ),
        side=side,
        filled_qty=qty,
        trade_fee=0.0,
        filled_avg_price=10.0,
        liquidity="",
        updated_at=DAY_START,
    )


@pytest.fixture
def ctx() -> Context:
    return Context(loader(aapl=make_bars([10.0, 11.0, 12.0])))


@pytest.mark.asyncio
async def test_rule_decides_on_fired_symbols_only(ctx) -> None:
    state = RunState(make_strategies(ctx, "r"))
    strategy = state.strategies["r"]

    if await state.decide_symbol("aapl", DAY_START):
        raise AssertionError("decided on a symbol no filter selected")

    state.set_universe("r", ["aapl"])
    decisions = await state.decide_symbol("aapl", DAY_START)
    if [s for s, _ in decisions] != [strategy] or strategy.rule.calls != [
        ("aapl", DAY_START, 0.0, 1.0)
    ]:
        raise AssertionError(f"unexpected decisions {decisions}")
    if state.symbol_owners != {"aapl": "r"}:
        raise AssertionError(
            f"strategy did not claim aapl: {state.symbol_owners}"
        )


@pytest.mark.asyncio
async def test_owner_and_open_orders_block_other_decisions(ctx) -> None:
    state = RunState(make_strategies(ctx, "first", "second"))
    state.set_universe("first", ["aapl"])
    state.set_universe("second", ["aapl"])
    first, second = state.strategies.values()

    decisions = await state.decide_symbol("aapl", DAY_START)
    if [s for s, _ in decisions] != [first] or second.rule.calls:
        raise AssertionError("a second strategy traded a claimed symbol")

    order = submitted("1", "aapl")
    first.open_orders[order.order_id] = OpenOrder(
        order, first, decisions[0][1]
    )
    if await state.decide_symbol("aapl", DAY_START + MINUTE):
        raise AssertionError("a rule decided while it had an open order")
    if len(first.rule.calls) != 1:
        raise AssertionError("the strategy with an open order was asked")


@pytest.mark.asyncio
async def test_fills_update_positions_and_release_symbols(ctx) -> None:
    state = RunState(make_strategies(ctx, "r"))
    state.set_universe("r", ["aapl"])
    strategy = state.strategies["r"]
    [(_, request)] = await state.decide_symbol("aapl", DAY_START)
    order = submitted("1", "aapl")
    strategy.open_orders[order.order_id] = OpenOrder(order, strategy, request)

    if await state.handle_trade(fill("other", 1.0)):
        raise AssertionError("applied another consumer's order")
    await state.handle_trade(fill("1", 0.4, partial=True))
    await state.handle_trade(fill("1", 0.6))
    if strategy.positions != {"aapl": 1.0} or state.get_open_orders_by_id():
        raise AssertionError(f"unexpected positions {strategy.positions}")
    if len(strategy.rule.fills) != 2 or state.symbol_owners != {"aapl": "r"}:
        raise AssertionError("fills not reported or symbol released")

    # the owner keeps deciding on its symbol once its filter drops it
    strategy.universe.clear()
    [(_, sell)] = await state.decide_symbol("aapl", DAY_START + MINUTE)
    order = submitted("2", "aapl", SELL)
    strategy.open_orders[order.order_id] = OpenOrder(order, strategy, sell)
    await state.handle_trade(fill("2", 1.0, SELL))
    if strategy.positions or state.symbol_owners:
        raise AssertionError("flat strategy still owns its symbol")


@pytest.mark.asyncio
async def test_cancel_notifies_rule_and_releases_symbol(ctx) -> None:
    state = RunState(make_strategies(ctx, "r"))
    state.set_universe("r", ["aapl"])
    strategy = state.strategies["r"]
    [(_, request)] = await state.decide_symbol("aapl", DAY_START)
    order = submitted("1", "aapl")
    strategy.open_orders[order.order_id] = OpenOrder(order, strategy, request)

    rejected = fill("1", 0.0)
    rejected.event = Order.EventType.rejected
    await state.handle_trade(rejected)
    if state.get_open_orders_by_id() or state.symbol_owners:
        raise AssertionError("rejected order kept")
    cancels = strategy.rule.cancels
    if [o.event for o in cancels] != [Order.EventType.rejected]:
        raise AssertionError(f"unexpected cancels {cancels}")


@pytest.mark.asyncio
async def test_portfolio_rule_gets_latest_signal_values(ctx) -> None:
    ctx.data_loader["msft"] = Bars(make_bars([20.0]))
    state = RunState(make_strategies(ctx, "r", portfolio="p"))
    state.set_universe("p", ["aapl", "msft"])
    strategy = state.strategies["p"]

    decisions = await state.decide_portfolio(strategy, DAY_START + 2 * MINUTE)
    [(positions, values)] = strategy.rule.calls
    if values.to_dict() != {"aapl": 1.0, "msft": 1.0}:
        raise AssertionError(f"unexpected signal values {values}")
    if [d[1].symbol for d in decisions] != ["aapl", "msft"]:
        raise AssertionError(f"unexpected decisions {decisions}")
    if state.symbol_owners != {"aapl": "p", "msft": "p"}:
        raise AssertionError(f"strategy did not claim: {state.symbol_owners}")


def test_signal_fired(ctx, caplog) -> None:
    signal = Always(ctx=ctx, name="s")

    # no bars of zzz were loaded
    if not signal.fired("aapl", DAY_START) or signal.fired("zzz", DAY_START):
        raise AssertionError("unexpected fired values")
    if "s failed on zzz" not in caplog.text:
        raise AssertionError("failed symbol not logged")


def test_signal_latest_values(ctx, caplog) -> None:
    ctx.data_loader["msft"] = Bars(make_bars([20.0]))
    signal = Always(ctx=ctx, name="s")

    # msft has a single bar, and no bars of zzz were loaded
    values = signal.latest(["aapl", "msft", "zzz"], DAY_START + 2 * MINUTE)

    if values.iloc[:2].to_dict() != {"aapl": 1.0, "msft": 1.0}:
        raise AssertionError(f"unexpected values {values}")
    if not math.isnan(values["zzz"]) or "s failed on zzz" not in caplog.text:
        raise AssertionError("failed symbol not logged as no value")
    if values.name != "s" or values.index.name != "symbol":
        raise AssertionError(f"unexpected labels {values}")


@pytest.mark.asyncio
async def test_strategy_that_requests_an_owned_symbol_is_deactivated(
    ctx, caplog
) -> None:
    ctx.data_loader["msft"] = Bars(make_bars([20.0]))
    state = RunState(make_strategies(ctx, "r", portfolio="p"))
    state.set_universe("p", ["aapl", "msft"])
    state.symbol_owners["msft"] = "r"
    strategies = state.strategies

    decisions = await state.decide_portfolio(strategies["p"], DAY_START)

    # the request for aapl is dropped too
    if decisions or state.symbol_owners != {"msft": "r"}:
        raise AssertionError(f"inactive strategy claimed symbols: {decisions}")
    if strategies["p"].active or not strategies["r"].active:
        raise AssertionError("wrong strategy deactivated")
    if list(strategies) != ["r", "p"]:
        raise AssertionError(f"unexpected strategies {strategies}")
    if "p requested msft, which r owns" not in caplog.text:
        raise AssertionError(f"collision not logged: {caplog.text}")


@pytest.mark.asyncio
async def test_halt_on_collision_raises_and_keeps_the_strategy(ctx) -> None:
    state = RunState(
        make_strategies(ctx, "r", portfolio="p"), halt_on_collision=True
    )
    state.set_universe("p", ["aapl"])
    state.symbol_owners["aapl"] = "r"

    with pytest.raises(OwnershipCollision, match="p requested aapl"):
        await state.decide_portfolio(state.strategies["p"], DAY_START)

    if not state.strategies["p"].active:
        raise AssertionError("strategy deactivated")


@pytest.mark.asyncio
async def test_inactive_strategy_keeps_its_positions_and_orders(ctx) -> None:
    ctx.data_loader["msft"] = Bars(make_bars([20.0]))
    state = RunState(make_strategies(ctx, "r", portfolio="p"))
    strategy = state.strategies["p"]
    state.set_universe("p", ["msft"])
    [(_, request)] = await state.decide_portfolio(strategy, DAY_START)
    order = submitted("1", "msft")
    strategy.open_orders[order.order_id] = OpenOrder(order, strategy, request)

    state.set_universe("p", ["aapl"])
    state.symbol_owners["aapl"] = "r"
    await state.decide_portfolio(strategy, DAY_START + MINUTE)
    await state.handle_trade(fill("1", 1.0))

    # the fill still applies, and no other strategy may trade the position
    if strategy.active or strategy.positions != {"msft": 1.0}:
        raise AssertionError(f"unexpected positions {strategy.positions}")
    if state.symbol_owners != {"aapl": "r", "msft": "p"}:
        raise AssertionError(f"unexpected owners {state.symbol_owners}")


@pytest.mark.asyncio
async def test_inactive_strategy_drops_its_universe_and_rule(ctx) -> None:
    state = RunState(make_strategies(ctx, "r", portfolio="p"))
    strategy = state.strategies["p"]
    state.set_universe("p", ["aapl"])
    state.symbol_owners["aapl"] = "r"
    await state.decide_portfolio(strategy, DAY_START)

    state.set_universe("p", ["msft"])
    await state.decide_portfolio(strategy, DAY_START + MINUTE)
    if strategy.active or strategy.universe:
        raise AssertionError(f"inactive strategy kept {strategy.universe}")
    if state.get_all_symbols() != {"aapl"} or len(strategy.rule.calls) != 1:
        raise AssertionError("inactive strategy still decides")


@pytest.mark.asyncio
async def test_inactive_strategy_runs_neither_rule_nor_signal(ctx) -> None:
    signals = {name: CountingAlways(ctx=ctx, name=name) for name in ("r", "q")}
    state = RunState(make_strategies(ctx, "r", "q", signals=signals))
    state.set_universe("r", ["aapl"])
    state.set_universe("q", ["aapl"])
    r, q = state.strategies.values()
    r.active = False

    decisions = await state.decide_symbol("aapl", DAY_START)

    if [strategy for strategy, _ in decisions] != [q]:
        raise AssertionError(f"unexpected decisions {decisions}")
    if r.rule.calls or signals["r"].computed:
        raise AssertionError("asked the rule or signal of a stopped strategy")
    if not signals["q"].computed:
        raise AssertionError("the active strategy's signal was not evaluated")


@pytest.mark.asyncio
async def test_signal_is_not_evaluated_on_another_strategys_symbol(
    ctx,
) -> None:
    signal = CountingAlways(ctx=ctx, name="r")
    state = RunState(make_strategies(ctx, "r", signals={"r": signal}))
    state.set_universe("r", ["aapl"])
    state.symbol_owners["aapl"] = "q"

    if await state.decide_symbol("aapl", DAY_START) or signal.computed:
        raise AssertionError("evaluated a signal for a symbol q owns")


@pytest.mark.asyncio
async def test_submit_places_sells_first(ctx) -> None:
    state = RunState(make_strategies(ctx, "r"))
    strategy = state.strategies["r"]
    buy_a, sell, buy_c = (
        OrderRequest("a", BUY, 1.0),
        OrderRequest("b", SELL, 1.0),
        OrderRequest("c", BUY, 1.0),
    )
    placed = []

    async def place(request):
        placed.append(request)

    await state.submit_order(
        [(strategy, r) for r in (buy_a, sell, buy_c)], place
    )
    if placed != [sell, buy_a, buy_c]:
        raise AssertionError(f"unexpected order of submissions {placed}")


@pytest.mark.asyncio
async def test_backtest_fills_at_next_open() -> None:
    ctx = Context(loader(aapl=make_bars([10.0, 11.0, 12.0])), backtesting=True)
    strategies = make_strategies(ctx, "r")
    session = Backtest(
        ctx, RunState(strategies), TimeScale.minute, buy_fee_percentage=1.0
    )

    await session.simulate_day(DAY_START, DAY_START + 3 * MINUTE)

    # buy at 9:31, sell at 9:32; the buy decided at 9:32 ends with the day
    trades = pd.DataFrame(session.trades)
    if list(trades.side) != ["buy", "sell"] or list(trades.price) != [
        11.0,
        12.0,
    ]:
        raise AssertionError(f"unexpected trades {trades}")
    if list(trades.time) != [DAY_START + MINUTE, DAY_START + 2 * MINUTE]:
        raise AssertionError(f"unexpected fill times {trades.time}")
    if trades.fee.iloc[0] != pytest.approx(0.11):
        raise AssertionError(f"unexpected fee {trades.fee}")
    if net_cash_flow(trades) != pytest.approx(12.0 - 11.0 - 0.11):
        raise AssertionError("unexpected cash flow")
    cancels = strategies["r"].rule.cancels
    if len(cancels) != 1 or session.state.get_open_orders_by_id():
        raise AssertionError("open order survived the end of the day")


@pytest.mark.asyncio
async def test_backtest_cancels_untouched_limit_order() -> None:
    ctx = Context(
        loader(aapl=make_bars([10.0, 11.0], lows=[9.0, 10.5])),
        backtesting=True,
    )
    strategies = make_strategies(ctx, "r")
    strategy = strategies["r"]
    strategy.rule = Recorder(
        ctx=ctx, name="r", signal=strategy.signal, limit_price=10.0
    )
    session = Backtest(ctx, RunState(strategies), TimeScale.minute)

    await session.simulate_day(DAY_START, DAY_START + 2 * MINUTE)

    if session.trades or len(strategy.rule.cancels) != 2:
        raise AssertionError(f"limit order filled: {session.trades}")


@pytest.mark.asyncio
async def test_backtest_skips_strategy_after_it_collides() -> None:
    ctx = Context(loader(aapl=make_bars([10.0, 11.0])), backtesting=True)
    selector = Sequence(
        ["aapl"], ["aapl"], ctx=ctx, name="p", recurrence=MINUTE
    )
    strategies = make_strategies(
        ctx, "r", portfolio="p", filters={"p": selector}
    )
    session = Backtest(ctx, RunState(strategies), TimeScale.minute)

    await session.simulate_day(DAY_START, DAY_START + 2 * MINUTE)

    # r claims aapl at 9:30, then p requests it in the same step; p and its
    # filter are due again at 9:31 but no longer run
    strategy = strategies["p"]
    calls = strategy.rule.calls
    if strategy.active or len(calls) != 1:
        raise AssertionError(f"inactive strategy decided {len(calls)} times")
    if selector.runs != 1:
        raise AssertionError(f"inactive filter ran {selector.runs} times")
    if [t["strategy"] for t in session.trades] != ["r"]:
        raise AssertionError(f"unexpected trades {session.trades}")


@pytest.mark.asyncio
async def test_backtest_halts_on_collision() -> None:
    ctx = Context(loader(aapl=make_bars([10.0, 11.0])), backtesting=True)
    strategies = make_strategies(ctx, "r", portfolio="p")
    session = Backtest(
        ctx, RunState(strategies, halt_on_collision=True), TimeScale.minute
    )

    with pytest.raises(OwnershipCollision, match="p requested aapl"):
        await session.simulate_day(DAY_START, DAY_START + 2 * MINUTE)


class Sequence(Filter):
    """Select the next list of symbols on each run, and count the runs."""

    def __init__(self, *selections, **kwargs):
        super().__init__(**kwargs)
        self.selections = list(selections)
        self.runs = 0

    async def run(self, now):
        self.runs += 1
        return self.selections.pop(0)


@pytest.mark.asyncio
async def test_backtest_filter_run_replaces_universe() -> None:
    bars = make_bars([10.0, 11.0])
    ctx = Context(loader(aapl=bars, msft=bars), backtesting=True)
    selector = Sequence(
        ["aapl", "msft"], ["aapl"], ctx=ctx, name="r", recurrence=MINUTE
    )
    strategies = make_strategies(ctx, "r", filters={"r": selector})
    session = Backtest(ctx, RunState(strategies), TimeScale.minute)

    await session.simulate_day(DAY_START, DAY_START + 2 * MINUTE)

    universe = strategies["r"].universe
    if universe != {"aapl"}:
        raise AssertionError(f"dropped symbol stayed in universe: {universe}")


@pytest.mark.asyncio
async def test_backtest_universe_lasts_until_next_filter_run() -> None:
    ctx = Context(loader(aapl=make_bars([10.0])), backtesting=True)
    selector = Sequence(
        ["aapl"], ctx=ctx, name="r", recurrence=pd.Timedelta(days=2)
    )
    strategies = make_strategies(ctx, "r", filters={"r": selector})
    session = Backtest(ctx, RunState(strategies), TimeScale.minute)

    await session.simulate_day(DAY_START, DAY_START + MINUTE)
    next_day = DAY_START + pd.Timedelta(days=1)
    await session.simulate_day(next_day, next_day + MINUTE)

    universe = strategies["r"].universe
    if selector.runs != 1 or universe != {"aapl"}:
        raise AssertionError(f"universe lost before the next run: {universe}")


@pytest.mark.asyncio
async def test_filter_without_recurrence_is_due_once_a_day(ctx) -> None:
    selector = Fixed(ctx=ctx, name="r")
    if not selector.is_due(DAY_START):
        raise AssertionError("filter not due before its first run")

    await selector.select(DAY_START)

    if selector.last_run != DAY_START or selector.is_due(DAY_START + MINUTE):
        raise AssertionError("filter due again on the day of its run")
    if not selector.is_due(DAY_START + pd.Timedelta(days=1)):
        raise AssertionError("filter not due on the next day")


@pytest.mark.asyncio
async def test_decide_portfolio_records_the_run_of_the_rule(ctx) -> None:
    state = RunState(make_strategies(ctx, portfolio="p"))
    strategy = state.strategies["p"]

    await state.decide_portfolio(strategy, DAY_START)

    rule = strategy.rule
    if rule.last_run != DAY_START or rule.is_due(DAY_START + MINUTE / 2):
        raise AssertionError("rule due before its recurrence elapsed")
    if not rule.is_due(DAY_START + MINUTE):
        raise AssertionError("rule not due once its recurrence elapsed")


@pytest.mark.asyncio
async def test_backtest_computes_signals_once_a_day() -> None:
    ctx = Context(loader(aapl=make_bars([10.0, 11.0, 12.0])), backtesting=True)
    signal = CountingAlways(ctx=ctx, name="r")
    strategies = make_strategies(ctx, "r", signals={"r": signal})
    session = Backtest(ctx, RunState(strategies), TimeScale.minute)

    day_end = DAY_START + 3 * MINUTE
    await session.simulate_day(DAY_START, day_end)
    next_day = DAY_START + pd.Timedelta(days=1)
    await session.simulate_day(next_day, next_day + MINUTE)

    # the signal fires on each bar of the first day; the second has no bars
    calls = strategies["r"].rule.calls
    if len(calls) != 3:
        raise AssertionError(f"unexpected calls {calls}")
    if signal.computed != [day_end, next_day + MINUTE]:
        raise AssertionError(f"unexpected computations {signal.computed}")


@pytest.mark.asyncio
async def test_backtest_steps_through_the_days_of_the_calendar(
    monkeypatch,
) -> None:
    ctx = Context(loader(), backtesting=True, asset_type=AssetType.CRYPTO)
    session = Backtest(ctx, RunState(make_strategies(ctx)), TimeScale.day)
    steps = []

    async def record(now):
        steps.append(now)

    monkeypatch.setattr(session, "simulate_timestep", record)

    await session.simulate_range(date(2026, 10, 3), date(2026, 10, 5))

    # crypto trades every day, and the day scale steps once at midnight
    expected = [
        pd.Timestamp(f"2026-10-0{day}", tz=clock.NY) for day in (3, 4, 5)
    ]
    if steps != expected:
        raise AssertionError(f"unexpected steps {steps}")


def test_context_creates_its_calendar_on_first_use(monkeypatch) -> None:
    created = []

    def factory(asset_type):
        created.append(asset_type)
        return CryptoCalendar()

    monkeypatch.setattr(base, "market_calendar_factory", factory)
    ctx = Context(loader(), asset_type=AssetType.CRYPTO)
    if created:
        raise AssertionError("created the calendar before its first use")
    if ctx.calendar is not ctx.calendar or created != [AssetType.CRYPTO]:
        raise AssertionError(f"unexpected calendar creations {created}")


def test_write_results(ctx, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    trades = pd.DataFrame(
        [
            [DAY_START, "r", "aapl", "buy", 1.0, 10.0, 0.0],
            [DAY_START, "r", "aapl", "sell", 1.0, 12.0, 0.5],
        ],
        columns=["time", "strategy", "symbol", "side", "qty", "price", "fee"],
    )
    strategies = make_strategies(ctx, "r", "idle")
    strategies["idle"].positions["msft"] = 2.0
    write_results("b", trades, strategies.values())

    if len(pd.read_csv(tmp_path / "b-trades.csv")) != 2:
        raise AssertionError("trades not written")
    summary = (tmp_path / "b-summary.txt").read_text()
    if "net cash flow: 1.50" not in summary or "'msft': 2.0" not in summary:
        raise AssertionError(f"unexpected summary {summary}")


def test_portfolio_filters() -> None:
    plan = [
        {
            "name": name,
            "filter": {"class": "Fixed", "filename": __file__},
            "signal": {"class": "Always", "filename": __file__},
            "rule": {"class": rule, "filename": __file__},
        }
        for name, rule in (("symbol", "Recorder"), ("portfolio", "Rebalance"))
    ]
    if portfolio_strategy_names(plan) != {"portfolio"}:
        raise AssertionError("wrong portfolio filters")
    if plan[1]["rule"] != {"class": "Rebalance", "filename": __file__}:
        raise AssertionError("portfolio_filters modified the trade plan")


class FakeStream:
    def __init__(self):
        self.queues = SymbolQueueMap()
        self.subscribed = []

    async def subscribe(self, symbols, events):
        self.subscribed += symbols


@pytest.mark.asyncio
async def test_router_assigns_and_forwards(monkeypatch) -> None:
    saved = []

    async def save_symbols(batch_id, symbols, scanner_name="momentum"):
        saved.append((scanner_name, symbols))

    monkeypatch.setattr(producer.TrendingTicker, "save_symbols", save_symbols)
    monkeypatch.setattr(producer.config, "batch_id", "b", raising=False)
    queues = [queue.Queue() for _ in range(3)]
    stream = FakeStream()
    router = producer.SymbolRouter(queues, {"pf"}, stream)

    await router.route("f", ["aapl", "msft"])
    await router.route("pf", ["spy"])
    await router.route("g", ["aapl"])

    if router.assigned != {"aapl": 0, "msft": 1, "spy": 0}:
        raise AssertionError(f"unexpected assignment {router.assigned}")
    if stream.subscribed != ["aapl", "msft", "spy"]:
        raise AssertionError(f"unexpected subscriptions {stream.subscribed}")
    if saved != [("f", ["aapl", "msft"]), ("pf", ["spy"])]:
        raise AssertionError(f"unexpected trending tickers {saved}")
    # every consumer gets its share of each run, even an empty one
    messages = [
        [
            (m["EV"], m["filter_name"], m["symbols"])
            for m in (q.get_nowait() for _ in range(q.qsize()))
        ]
        for q in queues
    ]
    result = QueueMessageType.FILTER_RESULT
    if messages != [
        [
            (result, "f", ["aapl"]),
            (result, "pf", ["spy"]),
            (result, "g", ["aapl"]),
        ],
        [(result, "f", ["msft"]), (result, "pf", []), (result, "g", [])],
        [(result, "f", []), (result, "pf", []), (result, "g", [])],
    ]:
        raise AssertionError(f"unexpected messages {messages}")


class Messages:
    """A consumer queue that holds some messages, then cancels its reader."""

    def __init__(self, *messages):
        self.messages = list(messages)

    def get(self, timeout=None):
        if not self.messages:
            raise asyncio.CancelledError
        return self.messages.pop(0)


@pytest.mark.asyncio
async def test_consumer_filter_result_replaces_universe(ctx) -> None:
    ctx.trader = FakeTrader()
    consumer = Consumer(ctx, RunState(make_strategies(ctx, "f", "g")), False)

    def result(filter_name, symbols):
        return {
            "EV": QueueMessageType.FILTER_RESULT,
            "filter_name": filter_name,
            "symbols": symbols,
        }

    await consumer.queue_consumer(
        Messages(
            result("f", ["aapl", "msft"]),
            result("f", ["aapl"]),
            result("g", ["msft"]),
            result("g", []),
            result("h", ["aapl"]),
        )
    )

    # h has no strategy in this run
    universes = {n: s.universe for n, s in consumer.state.strategies.items()}
    if universes != {"f": {"aapl"}, "g": set()}:
        raise AssertionError(f"unexpected universes {universes}")


@pytest.mark.asyncio
async def test_filter_runner_reports_empty_selection(ctx) -> None:
    results = queue.Queue()

    selector = Sequence([], ctx=ctx, name="f")

    await filters_runner.filter_runner(selector, results)

    if json.loads(results.get_nowait()) != {"filter_name": "f", "symbols": []}:
        raise AssertionError("empty selection not reported")


class FakeTrader:
    """Accept every order, and report a configured status for it."""

    def __init__(self, status=Order.EventType.open, filled_qty=0.0):
        self.status = status
        self.filled_qty = filled_qty
        self.submitted = []
        self.canceled = []

    async def submit_order(self, **kwargs):
        self.submitted.append(kwargs)
        return submitted(str(len(self.submitted)), kwargs["symbol"])

    async def is_order_completed(self, order_id, external_account_id=None):
        return self.status, 10.0, self.filled_qty, 0.0

    async def cancel_order(self, order):
        self.canceled.append(order.order_id)
        return True


@pytest.mark.asyncio
async def test_consumer_submits_and_applies_trade_updates(ctx) -> None:
    trader = FakeTrader()
    ctx.trader = trader
    consumer = Consumer(ctx, RunState(make_strategies(ctx, "r")), False)
    consumer.state.set_universe("r", ["aapl"])

    decisions = await consumer.state.decide_symbol("aapl", DAY_START)
    await consumer.state.submit_order(decisions, consumer._place)
    if [o["side"] for o in trader.submitted] != ["buy"]:
        raise AssertionError(f"unexpected orders {trader.submitted}")

    await consumer.state.handle_trade(fill("1", 1.0))
    if consumer.state.strategies["r"].positions != {"aapl": 1.0}:
        raise AssertionError("trade update not applied")


@pytest.mark.asyncio
async def test_consumer_cancels_stale_partially_filled_order(ctx) -> None:
    trader = FakeTrader(Order.EventType.partial_fill, filled_qty=0.25)
    ctx.trader = trader
    consumer = Consumer(ctx, RunState(make_strategies(ctx, "r")), False)
    consumer.state.set_universe("r", ["aapl"])
    decisions = await consumer.state.decide_symbol("aapl", DAY_START)
    await consumer.state.submit_order(decisions, consumer._place)

    [stale] = consumer.state.get_stale_orders(DAY_START + MINUTE)
    await consumer.check_order(stale, DAY_START + MINUTE)

    strategy = consumer.state.strategies["r"]
    rule = strategy.rule
    if trader.canceled != ["1"] or consumer.state.get_open_orders_by_id():
        raise AssertionError("stale order not canceled")
    if strategy.positions != {"aapl": 0.25}:
        raise AssertionError("reported partial fill not applied")
    if [o.filled_qty for o in rule.cancels] != [0.25]:
        raise AssertionError(f"unexpected cancels {rule.cancels}")


@pytest.mark.asyncio
async def test_consumer_stops_its_tasks_on_collision(ctx, monkeypatch) -> None:
    ctx.trader = FakeTrader()
    consumer = Consumer(ctx, RunState(make_strategies(ctx, "r"), True), False)

    async def collide(data):
        raise OwnershipCollision("r", "aapl", "q")

    monkeypatch.setattr(consumer, "handle_market_data", collide)

    # run raises although the lingering-order check would run forever
    with pytest.raises(OwnershipCollision):
        await asyncio.wait_for(
            consumer.run(Messages({"EV": QueueMessageType.MINUTE_BAR})), 5
        )


def test_bars_asks_loader_only_for_new_ranges() -> None:
    class Counting(Bars):
        def __init__(self, symbol_data):
            super().__init__(symbol_data)
            self.requests = []

        def __getitem__(self, key):
            self.requests.append((key.start, key.stop))
            return super().__getitem__(key)

    data = Counting(make_bars([10.0, 11.0, 12.0]))
    ctx = Context({"aapl": data})
    holiday = DAY_START - pd.Timedelta(days=3)

    ctx.bars("aapl", holiday, DAY_START + MINUTE)
    ctx.bars("aapl", holiday, DAY_START + MINUTE)
    bars = ctx.bars("aapl", holiday, DAY_START + 2 * MINUTE)

    if data.requests != [
        (holiday, DAY_START + MINUTE),
        (DAY_START + MINUTE, DAY_START + 2 * MINUTE),
    ]:
        raise AssertionError(f"unexpected loader requests {data.requests}")
    if len(bars) != 3 or len(ctx.bars("aapl", DAY_START, DAY_START)) != 1:
        raise AssertionError("bars returned the wrong rows")


def test_set_horizon_never_moves_it_back(ctx) -> None:
    ctx.set_horizon(DAY_START + MINUTE)
    ctx.set_horizon(DAY_START)

    if ctx.horizon != DAY_START + MINUTE:
        raise AssertionError(f"horizon moved back to {ctx.horizon}")
