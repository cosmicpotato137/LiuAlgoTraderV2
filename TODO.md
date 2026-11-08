# TODO

- [ ] Make every = None parameter on submit_order Optional
- [ ] A shared helper for starting and stopping websocket listeners: it's about three lines at each of two places, and each broker does something different around them.
- [ ] Refactor all side variables to use an enum rather than a string.
- [ ] Is it a vulnerability to accept num_consumers blindly from config without checking the cpu capacity? (liualgotrader/scripts/trader.py)
- [ ] Indicators are currently run out of Context. Should they instead be managed by RunState?
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