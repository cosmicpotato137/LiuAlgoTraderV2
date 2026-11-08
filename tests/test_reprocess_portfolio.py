import uuid

import pandas as pd
import pytest

from liualgotrader.common import clock
from liualgotrader.common.concurrency import get_event_loop
from liualgotrader.db.models.accounts import Account
from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.new_trades import Trade
from liualgotrader.db.models.portfolio import Portfolio
from liualgotrader.reprocess.portfolio import account_transactions


async def _create_portfolio_with_trades(portfolio_id: str) -> int:
    await Portfolio.save(portfolio_id, 5000, 0, {})
    batch_id = str(uuid.uuid4())
    await Portfolio.associate_batch_id_to_profile(portfolio_id, batch_id)
    algo_run = AlgoRun(strategy_name="test", batch_id=batch_id)
    await algo_run.save(env="TEST")

    now = pd.Timestamp.now(tz=clock.NY)
    for operation, price in (("buy", 100), ("sell", 110)):
        trade = Trade(
            algo_run_id=algo_run.algo_run_id,
            symbol="AAPL",
            operation=operation,
            qty=10,
            price=price,
            indicators={},
        )
        await trade.save(client_time=now, target_price=120)

    portfolio = await Portfolio.load_by_portfolio_id(portfolio_id)
    # a stale transaction that the recalculation must discard
    await Account.add_transaction(portfolio.account_id, -123.0)
    return portfolio.account_id


def test_account_transactions_rebuilds_from_trades():
    portfolio_id = str(uuid.uuid4())
    loop = get_event_loop()
    account_id = loop.run_until_complete(
        _create_portfolio_with_trades(portfolio_id)
    )

    account_transactions(portfolio_id)

    assert loop.run_until_complete(Account.get_balance(account_id)) == 5100
    transactions = loop.run_until_complete(
        Account.get_transactions(account_id)
    )
    assert sorted(transactions.amount.astype(float)) == [-1000.0, 1100.0]


def test_account_transactions_unknown_portfolio():
    with pytest.raises(ValueError):
        account_transactions(str(uuid.uuid4()))
