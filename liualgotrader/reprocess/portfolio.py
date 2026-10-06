"""Rebuild the account transactions of portfolios from their trades.

Functions
---------
account_transactions
    Rebuild the account transactions of a portfolio.
"""

from liualgotrader.analytics.analysis import load_trades_by_portfolio
from liualgotrader.common.concurrency import get_event_loop
from liualgotrader.db.models.accounts import Account
from liualgotrader.db.models.portfolio import Portfolio


async def _calc_account_transactions(portfolio_id: str, account_id: int):
    """Record an account transaction for each trade of a portfolio.

    Record buys as negative amounts and other trades as positive amounts.

    Parameters
    ----------
    portfolio_id: str
        The portfolio whose trades are recorded.
    account_id: int
        The account that receives the transactions.
    """
    _df = load_trades_by_portfolio(portfolio_id)
    for _, row in _df.iterrows():
        await Account.add_transaction(
            account_id,
            (row.qty * row.price) * (-1 if row.operation == "buy" else 1),
            row.tstamp,
        )


def account_transactions(portfolio_id: str):
    """Rebuild the account transactions of a portfolio from its trades.

    Reset the account balance to the account size and replace the existing
    transactions. Do not call it from asynchronous code.

    Parameters
    ----------
    portfolio_id: str
        The portfolio to rebuild.
    """
    loop = get_event_loop()
    _ = loop.run_until_complete(Portfolio.load_by_portfolio_id(portfolio_id))
    account_id, account_size = loop.run_until_complete(
        Portfolio.load_details(portfolio_id)
    )
    loop.run_until_complete(Account.clear_balance(account_id, account_size))
    loop.run_until_complete(Account.clear_account_transactions(account_id))

    loop.run_until_complete(
        _calc_account_transactions(
            portfolio_id=portfolio_id, account_id=account_id
        )
    )
