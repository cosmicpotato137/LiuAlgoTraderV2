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
gain_loss
    Persist and load the gain and trade analyses of strategy runs.
keystore
    Persist string values under unique keys in the database.
new_trades
    Persistence of the trade operations made by strategy runs.
optimizer
    Persist and load the batches run by optimizer sessions.
portfolio
    Persist and load trading portfolios.
ticker_data
    Persist and load ticker descriptions and daily price data.
ticker_snapshot
    Data type for the volume and daily change of a symbol.
tradeplan
    Load the trade plan entries that assign strategies to portfolios.
trending_tickers
    Persist and load the trending symbols found by scanners.
"""

from liualgotrader.db.models.accounts import Account, AccountTransaction
from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.gain_loss import GainLoss, TradeAnalysis
from liualgotrader.db.models.keystore import KeyStore
from liualgotrader.db.models.new_trades import NewTrade
from liualgotrader.db.models.optimizer import OptimizerRun
from liualgotrader.db.models.portfolio import Portfolio, PortfolioBatchId
from liualgotrader.db.models.ticker_data import StockOhlc, TickerData
from liualgotrader.db.models.ticker_snapshot import TickerSnapshot
from liualgotrader.db.models.tradeplan import (TradePlan,
                                               TradePlanExecutionAudit)
from liualgotrader.db.models.trending_tickers import TrendingTicker

__all__ = [
    "Account",
    "AccountTransaction",
    "AlgoRun",
    "GainLoss",
    "KeyStore",
    "NewTrade",
    "OptimizerRun",
    "Portfolio",
    "PortfolioBatchId",
    "StockOhlc",
    "TickerData",
    "TickerSnapshot",
    "TradeAnalysis",
    "TradePlan",
    "TradePlanExecutionAudit",
    "TrendingTicker",
]
