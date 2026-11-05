"""Liu Algo Trader, a framework for algorithmic trading and backtesting.

Modules
-------
consumer
    Run the rules of the trade plan on data streamed by the producer.
enhanced_backtest
    Backtest the filters, signals and rules of a trade plan on past data.
filters_runner
    Run the filters and pass new symbols to the producer.
producer
    Get market data from data providers and pump it to the consumers.

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
filters
    Built-in filters that select the symbols to trade.
fincalcs
    Financial calculations for use by strategies.
market_calendar
    Market calendar interface.
reprocess
    Recalculation of stored portfolio data.
scripts
    Command-line entry points of the framework.
strategy
    Strategy components and the run state that executes them.
stream
    Real-time market data streaming interface.
trade
    Broker interface for order execution.
vendors
    Vendor implementations of the trader, data and streaming interfaces.
"""
