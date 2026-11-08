## TODO

- [x] Make every = None parameter on submit_order Optional
- [x] A shared helper for starting and stopping websocket listeners: it's about three lines at each of two places, and each broker does something different around them. - common/websocket_listener.py, used by the Gemini and Tradier traders
- [x] Refactor all side variables to use an enum rather than a string. - submit_order takes an Order.FillSide; Tradier picks sell_short and buy_to_cover from the position
- [x] Is it a vulnerability to accept num_consumers blindly from config without checking the cpu capacity? (liualgotrader/scripts/trader.py) - No: whoever sets NUM_CONSUMERS can already run code as the trader. It now warns above 5 processes per physical core, and the derived count is at least 1
- [x] Indicators are currently run out of Context. Should they instead be managed by RunState? - No: they depend only on market data, signals create them before the RunState exists, and filters run without one
- [x] Restructure classes to follow the pattern: Filters, Indicators, Signals, Rules. These classes are composed as part of a Strategy
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
- [ ] Update database schema - not sure what's going on there

## Possible bugs

- Runs and trades aren't recorded: since the strategy refactor (197bdeb), nothing calls TraderAPI.create_session or saves a Trade, in trading or back-testing. The analytics in analytics/analysis.py, the portfolio app (including recalc) and the analysis notebooks only see runs and trades recorded before it.
- CPU_FACTOR is ignored: docs/source/Configuration.md and examples/.env.example describe it as the multiplication factor for the number of consumer processes (default 2.0), but since fcaedcd calc_num_consumer_processes uses a fixed 5 per idle core and nothing reads config.proc_factor.