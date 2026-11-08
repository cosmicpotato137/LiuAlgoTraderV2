import uuid
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import select, update

from liualgotrader.analytics import analysis
from liualgotrader.common import clock, config
from liualgotrader.common.types import AssetType, EnvType
from liualgotrader.db.models.accounts import Account
from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.new_trades import Trade
from liualgotrader.db.models.optimizer import OptimizerRun
from liualgotrader.db.models.portfolio import Portfolio
from liualgotrader.db.models.tradeplan import TradePlan
from liualgotrader.db.models.trending_tickers import TrendingTicker
from liualgotrader.db.session import create_db_connection, session_scope
from liualgotrader.trade.base import TraderAPI


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def new_run(strategy_name: str, batch_id: str, **kwargs) -> AlgoRun:
    run = AlgoRun(strategy_name=strategy_name, batch_id=batch_id)
    await run.save(env="TEST", **kwargs)
    return run


def new_trade(run: AlgoRun, symbol: str, operation: str, price, indicators):
    return Trade(
        algo_run_id=run.algo_run_id,
        symbol=symbol,
        operation=operation,
        qty=10,
        price=price,
        indicators=indicators,
    )


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_algo_run() -> bool:
    strategy, batch_id = unique("strategy"), unique("batch")
    run = await new_run(strategy, batch_id)
    ref = await new_run(strategy, batch_id, ref_algo_run_id=run.algo_run_id)
    if not run.algo_run_id or run.start_time is None:
        raise AssertionError("saved run missing database values")
    await run.update_end_time("done")
    if run.end_time is None or run.end_reason != "done":
        raise AssertionError("end time not set on the run")
    if run.start_time.tz != clock.NY or run.end_time.tz != clock.NY:
        raise AssertionError("run times not read back in New York time")

    details = await AlgoRun.get_batch_details(batch_id)
    if [d[0] for d in details] != [ref.algo_run_id, run.algo_run_id]:
        raise AssertionError(f"batch details not newest first: {details}")
    if details[1][2] != run.end_time or details[0][2] is not None:
        raise AssertionError("only the ended run should have an end time")
    if details[0][3] is None or "DSN" not in details[0][3]:
        raise AssertionError(f"parameters not a dict: {details[0][3]}")

    async with session_scope() as session:
        record = await session.get_one(AlgoRun, ref.algo_run_id)
    if record.ref_algo_run_id != run.algo_run_id:
        raise AssertionError("reference run not stored")
    if record.strategy_name != strategy or record.env != "TEST":
        raise AssertionError("run fields not stored")

    start_date = details[0][1].date()
    by_date = await AlgoRun.get_batch_list_by_date(start_date)
    runs = [r[0] for r in by_date.get(batch_id, [])]
    if runs != [ref.algo_run_id, run.algo_run_id]:
        raise AssertionError(f"batch missing by date: {by_date.get(batch_id)}")

    batches = await AlgoRun.get_batches(start_date=start_date)
    if not any(b[1] == batch_id and b[2] == strategy for b in batches):
        raise AssertionError(f"batch summary missing: {batches}")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_new_trade() -> bool:
    strategy, symbol = unique("strategy"), unique("SYM")
    run = await new_run(strategy, unique("batch"))
    other = await new_run(strategy, unique("batch"))

    buy = new_trade(run, symbol, "buy", 100.5, {"rsi": 30.0})
    await buy.save(
        clock.now(), stop_price=95.0, target_price=110.0, trade_fee=1.5
    )
    sell = new_trade(run, symbol, "sell", 105.25, {"x": float("nan")})
    await sell.save(clock.now())
    if not buy.trade_id or not sell.trade_id or buy.tstamp is None:
        raise AssertionError("saved trades missing database values")
    if sell.indicators != {}:
        raise AssertionError("NaN indicators not replaced")

    latest = await Trade.load_latest(symbol, strategy)
    if latest[:5] != (run.algo_run_id, 105.25, 0.0, 0.0, {}):
        raise AssertionError(f"unexpected latest trade {latest}")

    with pytest.raises(ValueError):
        await Trade.load_latest(symbol, unique("strategy"))

    if await Trade.get_run_symbols(run.algo_run_id) != [symbol]:
        raise AssertionError("run symbols missing")
    await Trade.expire_trade(buy.trade_id)
    await Trade.expire_trade(sell.trade_id)
    if await Trade.get_run_symbols(run.algo_run_id) != []:
        raise AssertionError("expired trades still listed")

    if await Trade.get_latest_algo_run_id(symbol) != run.algo_run_id:
        raise AssertionError("wrong latest run")
    await Trade.rename_algo_run_id(other.algo_run_id, run.algo_run_id, symbol)
    if await Trade.get_latest_algo_run_id(symbol) != other.algo_run_id:
        raise AssertionError("trades not moved")
    if await Trade.get_latest_algo_run_id(unique("SYM")) is not None:
        raise AssertionError("unknown symbol should have no run")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_trending_tickers() -> bool:
    batch_id = unique("batch")
    await TrendingTicker.save_symbols(batch_id, ["AAA", "BBB"])
    await TrendingTicker.save_symbols(batch_id, [])

    loaded = await TrendingTicker.load(batch_id)
    if sorted(s for s, _ in loaded) != ["AAA", "BBB"] or not loaded[0][1]:
        raise AssertionError(f"unexpected trending tickers {loaded}")

    with pytest.raises(Exception):
        await TrendingTicker.load(unique("batch"))

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_account_transaction_updates_account() -> bool:
    account_id = await Account.create(balance=100.0)
    await Account.add_transaction(account_id, 25.0)

    async with session_scope() as session:
        account = await session.get_one(Account, account_id)
    if account.balance != 125.0 or account.modify_tstamp is None:
        raise AssertionError("balance trigger did not update the account")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_optimizer_run() -> bool:
    session_id, batch_id, portfolio_id = (
        unique("session"),
        unique("batch"),
        unique("portfolio"),
    )
    await Portfolio.save(portfolio_id, 1000, 0, {})
    await Portfolio.associate_batch_id_to_profile(portfolio_id, batch_id)
    await OptimizerRun.save(session_id, batch_id, "{'a': 1}")

    result = await OptimizerRun.get_portfolio_ids_parameters(session_id)
    if result != [(portfolio_id, "{'a': 1}")]:
        raise AssertionError(f"unexpected session portfolios: {result}")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_list_portfolios() -> bool:
    portfolio_id = unique("portfolio")
    await Portfolio.save(
        portfolio_id, 1000, 0, {"p": 1}, asset_type=AssetType.CRYPTO
    )

    portfolios = await Portfolio.list_portfolios()
    ours = portfolios[portfolios.portfolio_id == portfolio_id]
    if list(ours[["portfolio_size", "asset_type"]].iloc[0]) != [
        1000,
        AssetType.CRYPTO,
    ]:
        raise AssertionError(f"unexpected portfolio listing: {ours}")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_trade_plan_new_entries() -> bool:
    portfolio_id, strategy = unique("portfolio"), unique("strategy")
    await Portfolio.save(portfolio_id, 1000, 0, {})
    created = clock.now()
    async with session_scope() as session:
        entry = TradePlan(
            portfolio_id=portfolio_id,
            start_date=clock.today() - pd.Timedelta(days=1),
            strategy_name=strategy,
            parameters={"k": 1},
        )
        session.add(entry)

    def names(entries):
        return {e.strategy_name: e.parameters for e in entries}

    minute = pd.Timedelta(minutes=1)
    try:
        if names(await TradePlan.load()).get(strategy) != {"k": 1}:
            raise AssertionError("active entry not loaded")
        if strategy not in names(
            await TradePlan.get_new_entries(created - minute)
        ):
            raise AssertionError("time before creation excluded")
        if strategy in names(
            await TradePlan.get_new_entries(clock.now() + minute)
        ):
            raise AssertionError("time after creation included")
        if strategy not in names(
            await TradePlan.get_new_entries(
                (created - minute).tz_convert("UTC")
            )
        ):
            raise AssertionError("UTC time before creation excluded")
    finally:
        # The entry has no strategy to run, so expire it before other tests
        # create the strategies of the active trade plan.
        async with session_scope() as session:
            await session.execute(
                update(TradePlan)
                .where(TradePlan.trade_plan_id == entry.trade_plan_id)
                .values(expire_tstamp=clock.now())
            )

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_analysis_loaders() -> bool:
    strategy, batch_id, symbol = (
        unique("strategy"),
        unique("batch"),
        unique("SYM"),
    )
    portfolio_id = unique("portfolio")
    await Portfolio.save(portfolio_id, 1000, 0, {})
    await Portfolio.associate_batch_id_to_profile(portfolio_id, batch_id)
    run = await new_run(strategy, batch_id)
    await new_trade(run, symbol, "buy", 10.0, {"a": 1}).save(
        pd.Timestamp("2026-01-05 10:00", tz=clock.NY), target_price=12.0
    )
    await new_trade(run, symbol, "sell", 11.0, {}).save(
        pd.Timestamp("2026-01-05 11:00", tz=clock.NY)
    )
    day = (await Trade.load_latest(symbol, strategy))[5].date()

    trades = await analysis.load_trades(day)
    ours = trades[trades.symbol == symbol]
    if list(ours.operation) != ["buy", "sell"] or ours.indicators.iloc[0] != {
        "a": 1
    }:
        raise AssertionError(f"unexpected trades: {ours}")
    if set(ours.batch_id) != {batch_id} or set(ours.strategy_name) != {
        strategy
    }:
        raise AssertionError("run columns missing")

    by_batch = await analysis.load_trades_by_batch_id(batch_id)
    if len(by_batch) != 2 or by_batch.client_time.dtype.kind != "M":
        raise AssertionError(f"unexpected batch trades: {by_batch}")

    by_portfolio = await analysis.load_trades_by_portfolio(portfolio_id)
    if list(by_portfolio.operation) != ["buy"]:
        raise AssertionError(f"unexpected portfolio trades: {by_portfolio}")

    if run.algo_run_id not in (await analysis.load_runs(day)).index:
        raise AssertionError("run missing")
    if batch_id not in set(
        (await analysis.load_batch_list(day, "TEST")).batch_id
    ):
        raise AssertionError("batch missing")
    if list((await analysis.load_traded_symbols(batch_id)).symbol) != [symbol]:
        raise AssertionError("traded symbol missing")

    period = await analysis.load_trades_for_period(
        "TEST", day, day + pd.Timedelta(days=1)
    )
    if len(period[period.symbol == symbol]) != 2:
        raise AssertionError("trades for period missing")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_tz_datetime_round_trip() -> bool:
    strategy = unique("strategy")
    run = await new_run(strategy, unique("batch"))
    # 01:30 occurs twice on 2024-11-03 in New York; this is the second, EST.
    client_time = pd.Timestamp("2024-11-03 06:30:00.123456", tz="UTC")
    trade = new_trade(run, unique("SYM"), "buy", 1.0, {})
    await trade.save(client_time.tz_convert(clock.NY))

    async with session_scope() as session:
        stored = await session.scalar(
            select(Trade.client_time).where(Trade.trade_id == trade.trade_id)
        )
    if not isinstance(stored, pd.Timestamp) or stored.tz != clock.NY:
        raise AssertionError(f"not read back in New York time: {stored!r}")
    if stored != client_time or stored.utcoffset() != pd.Timedelta(hours=-5):
        raise AssertionError(f"wrong time read back: {stored!r}")

    for invalid in (
        "2026-01-05 10:00:00",
        pd.Timestamp("2026-01-05 10:00"),
        datetime(2026, 1, 5, 10, tzinfo=timezone.utc),
        date(2026, 1, 5),
    ):
        with pytest.raises(Exception, match="time zone-aware pd.Timestamp"):
            await new_trade(run, unique("SYM"), "buy", 1.0, {}).save(invalid)

    return True


async def test_create_session_records_config_env(monkeypatch):
    monkeypatch.setattr(config, "env", EnvType.LIVE)
    run = await TraderAPI().create_session(unique("strategy"))

    async with session_scope() as session:
        record = await session.get_one(AlgoRun, run.algo_run_id)
    assert record.env == "LIVE"
