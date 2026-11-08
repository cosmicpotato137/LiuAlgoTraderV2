# Entry Points

The project has five console scripts, defined in `pyproject.toml:74-79`. All of them call `configure_logging()` first. The ones that trade read `tradeplan.toml` from `TRADEPLAN_DIR`, or from the current directory if that isn't set (`liualgotrader/common/config.py:40-45`).

## `trader`: live trading

`liualgotrader/scripts/trader.py:56` (`main_cli`) starts several processes that pass messages through multiprocessing queues.

1. Load the trade plan (`liualgotrader/scripts/trader.py:71-83`), create a batch ID, which is a UUID (`liualgotrader/scripts/trader.py:67`), and set the process start method to `spawn` (`liualgotrader/scripts/trader.py:65`).
2. Start N **consumer** processes, each with its own queue (`liualgotrader/scripts/trader.py:86-98`). N comes from `calc_num_consumer_processes` (`liualgotrader/common/concurrency.py:21`).
3. Start one **producer** process. It gets every consumer queue plus a scanner queue (`liualgotrader/scripts/trader.py:100-111`).
4. If the trade plan has a `[scanners]` section, start a **scanner** process (`liualgotrader/scripts/trader.py:113-123`).
5. Wait for all of them to finish. Ctrl-C kills them (`liualgotrader/scripts/trader.py:126-141`).

### Producer (`producer.py`)

The process entry is `producer_main` (`liualgotrader/producer.py:372`), which runs `producer_async_main` (`liualgotrader/producer.py:324`).

1. Connect to the database (`liualgotrader/producer.py:343`). Build a map that decides which consumer queue each symbol goes to (`liualgotrader/producer.py:344`).
2. Start the market-data stream (`liualgotrader/producer.py:345` → `run`, `liualgotrader/producer.py:309-310`). Alpaca, Polygon or Gemini is chosen by `DATA_CONNECTOR` (`liualgotrader/stream/factory.py:36-44`).
3. Start the broker trader (`liualgotrader/producer.py:347-348`), chosen by `LIU_BROKER` (`liualgotrader/trade/factory.py:44-57`). It subscribes to order updates and sends each one as a `trade_update` message to every consumer queue. For Alpaca, the subscription is at `liualgotrader/vendors/alpaca/trader.py:214`, the listener starts at `liualgotrader/vendors/alpaca/trader.py:538`, and `_trade_update_handler` sends the messages (`liualgotrader/vendors/alpaca/trader.py:1167`, `:1196-1197`). Gemini builds the message at `liualgotrader/vendors/gemini/trader.py:556` and Tradier at `liualgotrader/vendors/tradier/trader.py:878`.
4. Loop on the scanner queue (`scanner_input`, `liualgotrader/producer.py:153` → `scanners_iteration`, `liualgotrader/producer.py:108`). Each new symbol is assigned to a random consumer queue (`liualgotrader/producer.py:83-85`), subscribed to second bars, minute bars and trades (`liualgotrader/producer.py:140` → `subscribe_new_symbols`, `liualgotrader/producer.py:90`), and saved to `TrendingTicker` (`liualgotrader/producer.py:141`).
5. Every 5 minutes, check the database `TradePlan` table for new entries (`tradeplan_scanner`, `liualgotrader/producer.py:247`, `:264-273`). Send each one as a `new_strategy` message to a random consumer (`dispense_strategies`, `liualgotrader/producer.py:211`, `:225-237`).

### Scanner process (`scanners_runner.py`)

The process entry is `main` (`liualgotrader/scanners_runner.py:271`), which runs `async_main` (`liualgotrader/scanners_runner.py:242`).

1. Build the scanners (`create_scanners`, `liualgotrader/scanners_runner.py:142`). `momentum` is built in (`liualgotrader/scanners_runner.py:167-175` → `create_momentum_scanner`, `liualgotrader/scanners_runner.py:94`). Any other scanner is loaded from the `filename` in its config (`liualgotrader/scanners_runner.py:178-182` → `Scanner.get_scanner`, `liualgotrader/scanners/base.py:101`).
2. Run all scanners at the same time (`scanners_runner`, `liualgotrader/scanners_runner.py:187`, `:208-217`). Each one runs (`scanner_runner`, `liualgotrader/scanners_runner.py:41`, `:56`), puts a JSON list of `{symbol, target_strategy_name}` on the scanner queue (`liualgotrader/scanners_runner.py:62-72`), then waits its `recurrence` time (`liualgotrader/scanners_runner.py:77`). A scanner with no recurrence runs once (`liualgotrader/scanners_runner.py:74-75`).

### Consumer (`consumer.py`)

The process entry is `consumer_main` (`liualgotrader/consumer.py:1591`), which runs `consumer_async_main` (`liualgotrader/consumer.py:1528`).

1. Create strategies from `[strategies]` in the TOML file (`liualgotrader/consumer.py:1555` → `create_strategies_from_file`, `liualgotrader/consumer.py:1367`). Unless `file_only` is set, also create them from the database `TradePlan` table (`liualgotrader/consumer.py:1562-1567` → `create_strategies_from_db`, `liualgotrader/consumer.py:1445`). Set starting positions from each portfolio's past trades (`load_symbol_position`, `liualgotrader/consumer.py:1416`, called at `:1403-1411` and `:1485-1493`).
2. Run three tasks at the same time (`liualgotrader/consumer.py:1569-1586`):
   - **Queue consumer** (`queue_consumer`, `liualgotrader/consumer.py:1297`): handles each message by type (`liualgotrader/consumer.py:1322-1335`):
     - `trade_update` (`liualgotrader/consumer.py:1322-1325` → `handle_trade_update`, `liualgotrader/consumer.py:629`): updates the open order and position (`handle_trade_update_for_order`, `liualgotrader/consumer.py:562` → `update_partially_filled_order`, `:439`, or `update_filled_order`, `:505`), then calls the strategy's buy or sell callback (`do_callbacks`, `liualgotrader/consumer.py:403`).
     - `new_strategy` (`liualgotrader/consumer.py:1326-1333`): creates the strategy and adds it to the active list (`handle_new_strategy`, `liualgotrader/consumer.py:1499`).
     - Market data (`liualgotrader/consumer.py:1335` → `handle_data_queue_msg`, `:1239` → `handle_aggregate`, `:1186`): adds the bar to the `DataLoader` (`liualgotrader/consumer.py:1219` → `aggregate_bar_data`, `:722`). If the symbol already has an open order, it checks that order and cancels it if it's stale (`liualgotrader/consumer.py:1222-1225` → `order_inflight`, `:795`; stale check `should_cancel_order`, `:325`; cancel at `:874`). Otherwise it calls `strategy.run(...)` for each per-symbol strategy (`liualgotrader/consumer.py:1227` → `do_strategies`, `:1127` → `do_strategy`, `:1021`, `:1063`) and submits any order through the trader (`execute_strategy_result`, `liualgotrader/consumer.py:961` → `submit_order`, `:894`). Once a strategy rejects a symbol, it isn't run on that symbol again (recorded at `liualgotrader/consumer.py:1175-1178`, skipped by `_filter_strategies`, `:1085`).
   - **Periodic runner** (`periodic_runner`, `liualgotrader/consumer.py:269`): every 5 minutes (`liualgotrader/consumer.py:313`), calls `run_all` on the whole-portfolio strategies (`do_strategy_all`, `liualgotrader/consumer.py:182`), using the symbols each one last traded (`liualgotrader/consumer.py:295-299`).
   - **Lingering-order check** (`_cancel_lingering_orders`, `liualgotrader/consumer.py:236`): every 60 seconds (`liualgotrader/consumer.py:249`) while the market is open (`liualgotrader/consumer.py:255`), checks open orders and cancels stale ones (`liualgotrader/consumer.py:259-266`).

## `backtester from <date> [--to --scale --scanners --strats --asset --*-fee-percentage]`

The entry is `main_cli` (`liualgotrader/scripts/backtester.py:119`).

1. Parse the arguments (`liualgotrader/scripts/backtester.py:151-207`), load the trade plan (`liualgotrader/scripts/backtester.py:134-146`), and set `portfolio_value` and `risk` (`liualgotrader/scripts/backtester.py:147-149`).
2. `enhanced_backtest.backtest()` (`liualgotrader/scripts/backtester.py:209` → `liualgotrader/enhanced_backtest.py:828`) creates a batch ID (`liualgotrader/enhanced_backtest.py:865`) and calls `backtest_main` on a fresh event loop (`liualgotrader/enhanced_backtest.py:867-883`).
3. `backtest_main` (`liualgotrader/enhanced_backtest.py:744`) connects to the database (`:800`) and creates a `DataLoader(scale)` (`:802`). It creates the selected scanners (`:804-808` → `create_scanners`, `:63`) and strategies (`:810-812` → `create_strategies`, `:107`). Each strategy's `create()` saves an `AlgoRun` row (`liualgotrader/strategy/base.py:167`, `:178`, called from `Strategy.get_strategy` at `:448`).
4. Get the list of days (`backtest_time_range`, `liualgotrader/enhanced_backtest.py:674`). Equities use the Alpaca market calendar (`liualgotrader/enhanced_backtest.py:715-719`); crypto uses every calendar day (`liualgotrader/enhanced_backtest.py:720-723`).
5. Step through each day from start to end (`liualgotrader/enhanced_backtest.py:729-741` → `backtest_day`, `:568`), one minute or one day at a time (`liualgotrader/enhanced_backtest.py:617`, `:671`). At each step:
   1. Run any scanners that are due (`liualgotrader/enhanced_backtest.py:618` → `do_scanners`, `:153`). A scanner with no recurrence runs once per day (`liualgotrader/enhanced_backtest.py:177-179`).
   2. Prefetch data for symbols that were just scanned (`liualgotrader/enhanced_backtest.py:625-637`).
   3. For each strategy, take the symbols scanned for all strategies plus the ones targeted at it (`liualgotrader/enhanced_backtest.py:656-660`). Then (`do_strategy`, `liualgotrader/enhanced_backtest.py:494`, `:522-533`) call either `run_all`, which places sells before buys (`do_strategy_all`, `:362`, `:412-414`), or `run` for each symbol (`do_strategy_by_symbol`, `:431`, `:461`).
   4. Fill each order at that step's close: market orders at the close, limit orders only if the close is past the limit (`calculate_execution_price`, `liualgotrader/enhanced_backtest.py:198`). Call the buy or sell callback (`do_strategy_result`, `liualgotrader/enhanced_backtest.py:242`, `:297-312`), update the positions (`liualgotrader/enhanced_backtest.py:323-328`), and save a `NewTrade` row (`liualgotrader/enhanced_backtest.py:335-357`).
6. Log the batch ID, which you use to look up the results in analysis (`liualgotrader/enhanced_backtest.py:894`).

## `optimizer [--concurrency=N]`

The entry is `main_cli` (`liualgotrader/scripts/optimizer.py:255`).

1. Load the trade plan (`liualgotrader/scripts/optimizer.py:287-293` → `load_configuration`, `:233`), which must have an `[optimizer]` section (`liualgotrader/scripts/optimizer.py:295-297`) with dates (`liualgotrader/scripts/optimizer.py:301-306`), `hyperparameters` and `parameters`.
2. Build an iterator over every hyperparameter combination (`liualgotrader/scripts/optimizer.py:311-313` → `create_hyperparameters`, `:100`). Also build the `Parameter`s (`liualgotrader/scripts/optimizer.py:314` → `create_parameters`, `:74`), which get new values for every run, for example a new portfolio (`liualgotrader/scripts/optimizer.py:211`).
3. For each combination (`liualgotrader/scripts/optimizer.py:210`): copy the trade plan, write the values into their `strategies.<name>.<param>` paths (`realize`, `liualgotrader/scripts/optimizer.py:149`, applied at `:218`), and start a `backtest_iteration` process (`liualgotrader/scripts/optimizer.py:212-223`).
4. Each process (`backtest_iteration`, `liualgotrader/backtesting/optimizer.py:45`) runs `backtest_main` with daily steps, US equities and no fees (`liualgotrader/backtesting/optimizer.py:84-95`). If it succeeds, it saves an `OptimizerRun` row linking the session, the batch ID and the hyperparameter values (`liualgotrader/backtesting/optimizer.py:104-107` → `save_optimizer_session`, `:28`).
5. Processes run in batches: start N, wait for all N to finish, then start the next N (`liualgotrader/scripts/optimizer.py:225-228`).

## `liu`

The entry is `main_cli` (`liualgotrader/scripts/liu.py:313`).

- **`liu quickstart`** (`liualgotrader/scripts/liu.py:327-329` → `quickstart`, `:145`) is an interactive setup wizard:
  1. It asks whether you have an Alpaca account (`liualgotrader/scripts/liu.py:162-168`), and exits if `APCA_API_KEY_ID` or `APCA_API_SECRET_KEY` isn't set (`liualgotrader/scripts/liu.py:170-190`).
  2. It shows where the database is: SQLite by default, or Postgres if `DSN` is set (`liualgotrader/scripts/liu.py:192-207` → `_database_location`, `:65`).
  3. It lets you choose a folder for the samples (`liualgotrader/scripts/liu.py:209-226`).
  4. It runs the Alembic `upgrade_schema()` (`liualgotrader/scripts/liu.py:232` → `setup_db`, `:79`, `:90`), downloads the sample trade plan and strategies from GitHub (`liualgotrader/scripts/liu.py:233-234` → `setup_samples`, `:101`, `:123`), and prints next steps (`liualgotrader/scripts/liu.py:235-268`).
- **`liu create portfolio <amount> [--credit=X]`** (`liualgotrader/scripts/liu.py:332-359`) checks the amounts are positive (`liualgotrader/scripts/liu.py:335-339`, `:353-357`), calls `Portfolio.save` with a new UUID, and prints the ID (`create_portfolio`, `liualgotrader/scripts/liu.py:289`, `:299-310`).

## `portfolio <cmd>` (a Fire CLI)

The commands are registered at `liualgotrader/scripts/portfolio.py:208-218`.

- `create <size> <credit> <asset_type>`: saves a new portfolio (`liualgotrader/scripts/portfolio.py:106`).
- `list`: shows a table of all portfolios (`liualgotrader/scripts/portfolio.py:165`).
- `equity <id>`: shows current holdings with quantity and price (`liualgotrader/scripts/portfolio.py:41`).
- `account <id>`: shows cash transactions (`liualgotrader/scripts/portfolio.py:67`).
- `trades <id>`: shows the trade log (`liualgotrader/scripts/portfolio.py:137`).
- `recalc <id>` (`liualgotrader/scripts/portfolio.py:92` → `account_transactions`, `liualgotrader/reprocess/portfolio.py:36`): resets the account balance to its starting size (`liualgotrader/reprocess/portfolio.py:52`), deletes its transactions (`liualgotrader/reprocess/portfolio.py:53`), and replays every trade as a cash transaction, buys negative and sells positive (`_calc_account_transactions`, `liualgotrader/reprocess/portfolio.py:15`, `:28-31`).

## Known issues

- **`backtester` ignores `TRADEPLAN_DIR`:** it loads the trade plan from that folder, then reloads `tradeplan.toml` from the current directory at `liualgotrader/scripts/backtester.py:146`.
- **Unused code in `producer.py`:** `trade_run` (`liualgotrader/producer.py:197`) is never called, and at startup `run()` subscribes to a symbol list that is still empty (`liualgotrader/producer.py:311-316`). Neither causes a problem.
