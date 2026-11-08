"""Database models for runs, trades, portfolios and accounts.

Each model class maps one database table through the SQLAlchemy ORM and
carries the queries for that table. Together the models define the schema,
which the migrations in liualgotrader/db/migrations create and upgrade. Every
model is available from this package.

Modules
-------
accounts
    Persist and load accounts and their transactions.
algo_run
    Persist and load strategy runs and their batches.
base
    Declarative base, column types and SQL helpers shared by the models.
keystore
    Persist string values under unique keys in the database.
new_trades
    Persistence of the trade operations made by strategy runs.
optimizer
    Persist and load the batches run by optimizer sessions.
portfolio
    Persist and load trading portfolios.
tradeplan
    Load the trade plan entries that assign strategies to portfolios.
trending_tickers
    Persist and load the trending symbols found by filters.
"""

from liualgotrader.db.models.accounts import Account, AccountTransaction
from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.keystore import KeyStore
from liualgotrader.db.models.new_trades import Trade
from liualgotrader.db.models.optimizer import OptimizerRun
from liualgotrader.db.models.portfolio import Portfolio, PortfolioBatchId
from liualgotrader.db.models.tradeplan import TradePlan
from liualgotrader.db.models.trending_tickers import TrendingTicker

__all__ = [
    "Account",
    "AccountTransaction",
    "AlgoRun",
    "KeyStore",
    "OptimizerRun",
    "Portfolio",
    "PortfolioBatchId",
    "Trade",
    "TradePlan",
    "TrendingTicker",
]
