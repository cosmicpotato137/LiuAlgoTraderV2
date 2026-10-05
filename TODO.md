## Structural changes

- [ ] Restructure classes to follow the pattern: Filters, Indicators, Signals, Rules. These classes are composed as part of a Strategy
- [ ] Update database schema - not sure what's going on there
- [ ] Is it a vulnerability to accept num_consumers blindly from config without checking the cpu capacity? (liualgotrader/scripts/trader.py)
- [x] Update to use SQLite with optional postgres and MySQL
- [x] Add docstrings
- [x] Update python and package versions
- [x] Get readthedocs working
- [x] Updated to better config handling
- [x] Reformat to use vendor for api wrappers
  - [x] Abstract out the broker and data apis and create a wrapper for alpaca - was already done
- [x] Use an ORM to manage database. Might need to make some updates to include the OHLC timescale?

## Future plans

- [ ] Handling for multiple simultaneous brokers and accounts

## Possible bugs

- Tradier always fails: trade/trader_factory.py:26-27 stores the Tradier trader under "TRADIER" but returns traders["TradierTrader"], so every call raises KeyError.
- Invalid SQL: models/algo_run.py's get_batch_list_by_date puts ORDER BY before WHERE, which Postgres rejects.
- Broken queries: analytics/analysis.py:94,149 has literal \x1f control characters instead of newlines in the SQL f-strings of load_trades and load_runs, so those queries are likely broken.
- Setting ignored: in miners/stock_cluster.py, the num_workers setter checks the value but never stores it.
- GeminiTrader.cancel_order returns a dict despite its -> bool annotation.
- enhanced_backtest.py checks the signature of buy_callback when handling sells.
- Several queue.Full handlers raise KeyError on event['sym'], because that key no longer exists by then.
- reprocess/portfolio.py is missing an await and calls a Portfolio.load_details method that doesn't exist.
- SQL is built with f-strings from arguments in a few places, which is an injection risk.
- Retries on 429 and 502 responses have no limit.
- Runs recorded as env "unknown": Strategy.create in strategies/base.py and Trader.create_session in trade/base.py call AlgoRun.save() without env, so every run is saved with env "unknown" and filters on env (analytics/analysis.py load_trades_for_period and calc_revenue) miss new runs. Passing config.env would fix it.