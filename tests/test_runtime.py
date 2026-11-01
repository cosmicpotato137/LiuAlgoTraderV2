"""Tests of the run state, the backtester and the producer's symbol routing.

The components here read synthetic bars, so the tests need no credentials.
"""

import queue

import pandas as pd
import pytest

from liualgotrader import producer
from liualgotrader.common import clock
from liualgotrader.common.types import (
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
from liualgotrader.strategy.new_base import (
    Context,
    Filter,
    OrderRequest,
    PortfolioRule,
    Signal,
    StrategyGraph,
    SymbolRule,
    portfolio_filters,
    select_rules,
)
from liualgotrader.strategy.runtime import RunState, sells_first

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
    """Buy when flat and fired, then sell the position on the next call."""

    def __init__(self, qty=1.0, limit_price=None, **kwargs):
        super().__init__(**kwargs)
        self.qty = qty
        self.limit_price = limit_price
        self.calls = []
        self.fills = []
        self.cancels = []

    async def decide(self, symbol, now, position, fired):
        self.calls.append((symbol, now, position, dict(fired)))
        if position:
            return [OrderRequest(symbol, SELL, abs(position))]
        if fired:
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
    """Record the signal table and buy one of each symbol with a value."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tables = []

    async def decide(self, now, positions, signals):
        self.tables.append((positions, signals))
        return [
            OrderRequest(symbol, BUY, 1.0)
            for symbol, value in signals["sig"].items()
            if value > 0
        ]


def make_graph(ctx, *rule_names, portfolio=None, filters=None):
    """Return a graph with the Always signal on filter f and Recorder rules."""
    signal = Always(ctx=ctx, name="sig")
    rules = {
        name: Recorder(ctx=ctx, name=name, signals=[signal])
        for name in rule_names
    }
    if portfolio:
        rules[portfolio] = Rebalance(
            ctx=ctx, name=portfolio, signals=[signal], recurrence=MINUTE
        )
    return StrategyGraph(
        filters=filters or {},
        signals={"sig": signal},
        rules=rules,
        signal_filters={"sig": ["f"]},
        rule_signals={name: ["sig"] for name in rules},
    )


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
    state = RunState(make_graph(ctx, "r"))
    rule = state.graph.rules["r"]

    if await state.decide_symbol("aapl", DAY_START):
        raise AssertionError("decided on a symbol no filter selected")

    state.add_symbol("f", "aapl")
    decisions = await state.decide_symbol("aapl", DAY_START)
    if [r for r, _ in decisions] != [rule] or rule.calls != [
        ("aapl", DAY_START, 0.0, {"sig": 1.0})
    ]:
        raise AssertionError(f"unexpected decisions {decisions}")
    if state.owners != {"aapl": "r"}:
        raise AssertionError(f"rule did not claim aapl: {state.owners}")


@pytest.mark.asyncio
async def test_owner_and_open_orders_block_other_decisions(ctx) -> None:
    state = RunState(make_graph(ctx, "first", "second"))
    state.add_symbol("f", "aapl")
    first, second = state.graph.rules.values()

    decisions = await state.decide_symbol("aapl", DAY_START)
    if [r for r, _ in decisions] != [first] or second.calls:
        raise AssertionError("a second rule traded a claimed symbol")

    state.add_open_order(submitted("1", "aapl"), first, decisions[0][1])
    if await state.decide_symbol("aapl", DAY_START + MINUTE):
        raise AssertionError("a rule decided while it had an open order")
    if len(first.calls) != 1:
        raise AssertionError("the rule with an open order was asked")


@pytest.mark.asyncio
async def test_fills_update_positions_and_release_symbols(ctx) -> None:
    state = RunState(make_graph(ctx, "r"))
    state.add_symbol("f", "aapl")
    rule = state.graph.rules["r"]
    [(_, request)] = await state.decide_symbol("aapl", DAY_START)
    state.add_open_order(submitted("1", "aapl"), rule, request)

    if await state.handle_trade(fill("other", 1.0)):
        raise AssertionError("applied another consumer's order")
    await state.handle_trade(fill("1", 0.4, partial=True))
    await state.handle_trade(fill("1", 0.6))
    if state.positions["r"] != {"aapl": 1.0} or state.open_orders:
        raise AssertionError(f"unexpected state {state.positions}")
    if len(rule.fills) != 2 or state.owners != {"aapl": "r"}:
        raise AssertionError("fills not reported or symbol released")

    # the owner keeps deciding on its symbol even without a fired signal
    state.universes.clear()
    [(_, sell)] = await state.decide_symbol("aapl", DAY_START + MINUTE)
    state.add_open_order(submitted("2", "aapl", SELL), rule, sell)
    await state.handle_trade(fill("2", 1.0, SELL))
    if state.positions["r"] or state.owners:
        raise AssertionError("flat rule still owns its symbol")


@pytest.mark.asyncio
async def test_cancel_notifies_rule_and_releases_symbol(ctx) -> None:
    state = RunState(make_graph(ctx, "r"))
    state.add_symbol("f", "aapl")
    rule = state.graph.rules["r"]
    [(_, request)] = await state.decide_symbol("aapl", DAY_START)
    state.add_open_order(submitted("1", "aapl"), rule, request)

    rejected = fill("1", 0.0)
    rejected.event = Order.EventType.rejected
    await state.handle_trade(rejected)
    if state.open_orders or state.owners:
        raise AssertionError("rejected order kept")
    if [o.event for o in rule.cancels] != [Order.EventType.rejected]:
        raise AssertionError(f"unexpected cancels {rule.cancels}")


@pytest.mark.asyncio
async def test_portfolio_rule_gets_latest_signal_values(ctx) -> None:
    ctx.data_loader["msft"] = Bars(make_bars([20.0]))
    state = RunState(make_graph(ctx, "r", portfolio="p"))
    state.add_symbol("f", "aapl")
    state.add_symbol("f", "msft")
    state.owners["msft"] = "r"
    rule = state.graph.rules["p"]

    decisions = await state.decide_portfolio(rule, DAY_START + 2 * MINUTE)
    [(positions, table)] = rule.tables
    if list(table.index) != ["aapl", "msft"] or list(table.sig) != [1, 1]:
        raise AssertionError(f"unexpected signal table {table}")
    if [d[1].symbol for d in decisions] != ["aapl"]:
        raise AssertionError("portfolio rule traded a symbol it doesn't own")


def test_sells_first() -> None:
    buy = (None, OrderRequest("a", BUY, 1.0))
    sell = (None, OrderRequest("b", SELL, 1.0))
    if sells_first([buy, sell]) != [sell, buy]:
        raise AssertionError("buys before sells")


@pytest.mark.asyncio
async def test_backtest_fills_at_next_open() -> None:
    ctx = Context(loader(aapl=make_bars([10.0, 11.0, 12.0])), backtesting=True)
    graph = make_graph(ctx, "r", filters={"f": Fixed(ctx=ctx, name="f")})
    session = Backtest(ctx, graph, TimeScale.minute, buy_fee_percentage=1.0)

    await session.run_day(DAY_START, DAY_START + 3 * MINUTE)

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
    if len(graph.rules["r"].cancels) != 1 or session.state.open_orders:
        raise AssertionError("open order survived the end of the day")


@pytest.mark.asyncio
async def test_backtest_cancels_untouched_limit_order() -> None:
    ctx = Context(
        loader(aapl=make_bars([10.0, 11.0], lows=[9.0, 10.5])),
        backtesting=True,
    )
    graph = make_graph(ctx, filters={"f": Fixed(ctx=ctx, name="f")})
    graph.rules["r"] = Recorder(
        ctx=ctx, name="r", signals=[graph.signals["sig"]], limit_price=10.0
    )
    graph.rule_signals["r"] = ["sig"]
    session = Backtest(ctx, graph, TimeScale.minute)

    await session.run_day(DAY_START, DAY_START + 2 * MINUTE)

    rule = graph.rules["r"]
    if session.trades or len(rule.cancels) != 2:
        raise AssertionError(f"limit order filled: {session.trades}")


def test_write_results(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    trades = pd.DataFrame(
        [
            [DAY_START, "r", "aapl", "buy", 1.0, 10.0, 0.0],
            [DAY_START, "r", "aapl", "sell", 1.0, 12.0, 0.5],
        ],
        columns=["time", "rule", "symbol", "side", "qty", "price", "fee"],
    )
    write_results("b", trades, {"r": {}, "idle": {"msft": 2.0}})

    if len(pd.read_csv(tmp_path / "b-trades.csv")) != 2:
        raise AssertionError("trades not written")
    summary = (tmp_path / "b-summary.txt").read_text()
    if "net cash flow: 1.50" not in summary or "'msft': 2.0" not in summary:
        raise AssertionError(f"unexpected summary {summary}")


def test_select_rules() -> None:
    plan = {
        "filters": {"f1": {}, "f2": {}},
        "signals": {"s1": {"filters": ["f1"]}, "s2": {"filters": ["f2"]}},
        "rules": {"r1": {"signals": ["s1"]}, "r2": {"signals": ["s2"]}},
    }
    selected = select_rules(plan, ["r1"])
    if [list(selected[k]) for k in ("filters", "signals", "rules")] != [
        ["f1"],
        ["s1"],
        ["r1"],
    ]:
        raise AssertionError(f"unexpected selection {selected}")
    if select_rules(plan, None) != plan:
        raise AssertionError("no selection should keep every rule")
    with pytest.raises(ValueError):
        select_rules(plan, ["missing"])


def test_portfolio_filters() -> None:
    plan = {
        "filters": {"f1": {}, "f2": {}},
        "signals": {"s1": {"filters": ["f1"]}, "s2": {"filters": ["f2"]}},
        "rules": {
            "symbol": {
                "class": "Recorder",
                "filename": __file__,
                "signals": ["s1"],
            },
            "portfolio": {
                "class": "Rebalance",
                "filename": __file__,
                "signals": ["s2"],
            },
        },
    }
    if portfolio_filters(plan) != {"f2"}:
        raise AssertionError("wrong portfolio filters")


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
    first = [queues[0].get_nowait() for _ in range(queues[0].qsize())]
    if [(m["EV"], m["symbol"], m["filter_name"]) for m in first] != [
        (QueueMessageType.FILTER_RESULT, "aapl", "f"),
        (QueueMessageType.FILTER_RESULT, "spy", "pf"),
        (QueueMessageType.FILTER_RESULT, "aapl", "g"),
    ]:
        raise AssertionError(f"unexpected messages {first}")


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
    consumer = Consumer(ctx, make_graph(ctx, "r"), False)
    consumer.state.add_symbol("f", "aapl")

    await consumer.submit(
        await consumer.state.decide_symbol("aapl", DAY_START)
    )
    if [o["side"] for o in trader.submitted] != ["buy"]:
        raise AssertionError(f"unexpected orders {trader.submitted}")

    await consumer.state.handle_trade(fill("1", 1.0))
    if consumer.state.positions["r"] != {"aapl": 1.0}:
        raise AssertionError("trade update not applied")


@pytest.mark.asyncio
async def test_consumer_cancels_stale_partially_filled_order(ctx) -> None:
    trader = FakeTrader(Order.EventType.partial_fill, filled_qty=0.25)
    ctx.trader = trader
    consumer = Consumer(ctx, make_graph(ctx, "r"), False)
    consumer.state.add_symbol("f", "aapl")
    await consumer.submit(
        await consumer.state.decide_symbol("aapl", DAY_START)
    )

    [stale] = consumer.state.stale_orders(DAY_START + MINUTE)
    await consumer.check_order(stale, DAY_START + MINUTE)

    rule = consumer.state.graph.rules["r"]
    if trader.canceled != ["1"] or consumer.state.open_orders:
        raise AssertionError("stale order not canceled")
    if consumer.state.positions["r"] != {"aapl": 0.25}:
        raise AssertionError("reported partial fill not applied")
    if [o.filled_qty for o in rule.cancels] != [0.25]:
        raise AssertionError(f"unexpected cancels {rule.cancels}")


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
