"""Liu Algo Trader, a framework for algorithmic trading and backtesting.

Modules
-------
consumer
    Execute strategies on streaming data received from the producer.
enhanced_backtest
    Backtest scanners and strategies on past market data.
producer
    Get market data from data providers and pump it to the consumers.
scanners_runner
    Run the scanners and pass new symbols to the producer.

Subpackages
-----------
analytics
    Analysis of trading and backtesting results.
common
    Configuration, data access, shared types and utilities.
data
    Historical market data interface.
db
    Database access through the SQLAlchemy ORM.
fincalcs
    Financial calculations for use by strategies.
miners
    Data miners that run outside trading hours.
reprocess
    Recalculation of stored portfolio data.
scanners
    Scanners that select the symbols to trade.
scripts
    Command-line entry points of the framework.
strategies
    The base class for trading strategies.
stream
    Real-time market data streaming interface.
trade
    Broker interface for order execution.
vendors
    Vendor implementations of the trader, data and streaming interfaces.
"""
