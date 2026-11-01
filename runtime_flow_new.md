# Entry Points

The project has five console scripts, defined in `pyproject.toml`. All of them call `configure_logging()` first. The ones that trade read `tradeplan.toml` from `TRADEPLAN_DIR`, or from the current directory if that isn't set.

## Strategy components

A strategy is no longer one class. The trade plan wires four kinds of component into a `StrategyGraph` (`liualgotrader/strategy/new_base.py`).

| Component | Reads | Returns | Runs in |
|---|---|---|---|
| `Filter` (replaces `Scanner`) | the market at `now` | symbols to watch | filter process (live), backtester |
| `Indicator` | one symbol's bars through `now` | DataFrame indexed by bar time | consumer, backtester |
| `Signal` | one symbol's indicators through `now` | float Series: the sign is the direction, the magnitude (up to 1) is the confidence, NaN means no prediction | consumer, backtester |
| `SymbolRule` | the signals that fired for one symbol, and its position in that symbol | `OrderRequest`s | consumer, backtester |
| `PortfolioRule` | the latest signal values for all its symbols, and its positions | `OrderRequest`s | consumer 0 (live), backtester |

How the parts fit together:

- **Links.** A signal lists one or more filters and evaluates every symbol they select. A rule lists one or more signals. Indicators aren't in the trade plan: a signal creates the ones it needs with `Indicator.create(ctx, ...)`, which returns one shared instance for each class and set of parameters.
- **Context.** Each run creates one `Context`. A run is a consumer process, the filter process or a backtest. The context holds the `DataLoader`, an optional trader for read-only queries, the shared indicators and the cache versions. It replaces module globals and the class-level `__instances` and `__data` dicts, so a new backtest, test or optimizer iteration starts clean by creating a new context.
- **Time.** `now` is the timestamp of the latest completed bar. `compute()` in indicators and signals must be causal: each row can use only data stamped at or before it. `Context.bars()` never returns a bar stamped after `now`.
- **Memoization.** `Indicator.get` and `Signal.get` cache results for each symbol. A cached result is reused while it covers `now` and the symbol's bars haven't changed. The runtime calls `ctx.invalidate(symbol)` whenever it writes a bar.
- **Orders.** Rules return `OrderRequest`s and never call the trader. The runtime submits them when trading live and simulates fills when backtesting, so the same rule runs unchanged in both. Within one step, the runtime submits sells before buys.
- **Ownership.** A position in a symbol belongs to the rule that opened it until the position is flat. Meanwhile, no other rule is asked to decide on that symbol. A rule isn't asked to decide on a symbol while it has an open order for it. A rule hears about its orders through `on_fill` and `on_cancel`, which replace `buy_callback` and `sell_callback`.
- **Loading.** Every trade plan entry has a `class`. With a `filename`, `class` names a class in that file. Without one, it's a dotted import path, which is how built-ins like momentum are named. Each file is loaded once under its own module name, and load errors raise exceptions instead of calling `exit(0)`.

## Trade plan format

The table key is the instance name, and `class` names the class. This lets two entries use the same class with different settings. Every setting not listed here is passed to the class's `__init__` as a keyword argument, so a misspelled setting raises `TypeError` instead of being ignored.

```toml
# how many minutes before the end of the trading day to enforce liquidation
# market_liquidation_end_time_minutes = 15

# symbol filters; there may be several
[filters.momentum1]
class = "liualgotrader.filters.momentum.Momentum"

# scan for tickers with minimal volume since day start
min_volume = 30000
# minimum daily percentage change
today_change_percent = 3.5
# minimum last day dollar volume
min_last_dv = 500000
max_share_price = 20.0
min_share_price = 2.0
# how many minutes from market open to start running the filter
from_market_open = 15
# minutes between runs; without it, the filter runs once a day
# recurrence = 5

# signals; each one evaluates the symbols of the filters it lists
[signals.breakout]
class = "MySignal"
filename = "examples/my_signal.py"
filters = ["momentum1"]
check_patterns = true

# rules; each one decides on the signals it lists
[rules.breakout_long]
class = "MyBuy"
filename = "examples/my_rule.py"
signals = ["breakout"]
# times of day, New York time
buy_window_start = "09:45"
buy_window_end = "15:30"
# position sizing belongs to the rule now
portfolio_value = 25000.0
risk = 0.001

# a PortfolioRule must have a recurrence, in minutes
[rules.rebalance]
class = "MyRebalance"
filename = "examples/my_rule.py"
signals = ["breakout"]
recurrence = 5
```

## `trader`: live trading

`scripts/trader.py` starts several processes that pass messages through multiprocessing queues.

1. Load the trade plan, create a batch ID (a UUID), and set the process start method to `spawn`.
2. Start N **consumer** processes, each with its own queue. Only consumer 0 runs portfolio rules.
3. Start one **producer** process. It gets every consumer queue plus a filter queue.
4. Start a **filter** process. The trade plan must have a `[filters]` section, or the trader exits with an error.
5. Wait for all of them to finish. Ctrl-C kills them.

### Producer (`producer.py`)

1. Connect to the database and build the map that decides which consumer queue each symbol goes to. Find the *portfolio filters*: the filters that feed a `PortfolioRule` through its signals. This loads the rule classes but doesn't create the rules.
2. Start the market-data stream (Alpaca, Polygon or Gemini, chosen by `DATA_CONNECTOR`).
3. Start the broker trader (chosen by `LIU_BROKER`). It subscribes to order updates and sends each one as a `trade_update` message to every consumer queue.
4. Loop on the filter queue. For each `{filter_name, symbols}`:
   1. Assign each new symbol a consumer queue: consumer 0 for a portfolio filter, and otherwise the consumer with the fewest symbols. The assignment never changes. Subscribe the new symbols to second bars, minute bars and trades, and save them to `TrendingTicker` with their filter name.
   2. Send every consumer `{EV: "filter_result", symbols, filter_name}` with the symbols assigned to it, even when there are none, so that each consumer can replace the filter's universe. Already subscribed symbols are included, so that a symbol picked by a second filter reaches that filter's signals.

The producer no longer polls the `TradePlan` table or sends `new_strategy` messages.

### Filter process (`filters_runner.py`)

1. Create a `Context` with its own `DataLoader` and the broker trader, which the momentum filter asks for tradeable symbols. Create the filters with `create_filters()`.
2. Run all filters at the same time. Each one calls `run(clock.now())`, puts a JSON object `{filter_name, symbols}` on the filter queue, even when it selects no symbols, then waits for its `recurrence`. A filter with no recurrence runs once.

### Consumer (`consumer.py`)

1. Create a `Context` with a `DataLoader` and the trader, and build the `StrategyGraph` with `with_filters=False`. No loading from the database. Will rebuild later.
2. Keep the run state in one object created here, instead of the `trading_data` module globals: each filter's universe (the symbols of its latest run on this consumer), each rule's positions, the open orders by order ID with the rule that placed them, and the owner of each symbol.
3. Run three tasks at the same time:
   - **Queue consumer:** handles each message by its `EV` with a `match` statement, and logs an error for an unknown type:
     - `trade_update`: looks up the open order by its ID, and ignores the update if this consumer has no such order, because updates go to every consumer. Otherwise it updates the rule's position, releases the symbol if the position is now flat, and calls `rule.on_fill(trade)`. When the order is canceled, rejected or expires, it drops the open order and calls `rule.on_cancel(order)`.
     - `filter_result`: replaces the filter's universe with the symbols, as the backtester does.
     - Market data: adds the bar to the `DataLoader` and calls `ctx.invalidate(symbol)`. If the symbol has a stale open order, it checks the order and cancels it. Then, for a minute bar only (`AM`), with `now` set to the bar's timestamp:
       1. For each signal whose filters selected the symbol, it gets `signal.at(symbol, now)`. A value other than NaN means the signal fired.
       2. For each `SymbolRule` that is linked to a fired signal or owns the symbol, it skips the rule if the rule has an open order for the symbol or another rule owns it. Otherwise it calls `rule.decide(symbol, now, position, fired)`, where `fired` holds only that rule's fired signals.
       3. It submits the returned orders, sells before buys, and records each open order with its rule. The order that opens a position makes its rule the symbol's owner.
   - **Periodic runner** (consumer 0 only): runs each `PortfolioRule` every `recurrence`. It builds a DataFrame from the latest value of each of the rule's signals for every symbol in their filters' universes, calls `rule.decide(now, positions, signals)`, and submits the orders, sells before buys.
   - **Lingering-order check:** every 60 seconds while the market is open, checks open orders, cancels stale ones, and calls each canceled order's `rule.on_cancel`.

## `backtester from <date> [--to --scale --rules --asset --*-fee-percentage]`

1. Parse the arguments and load the trade plan. `--rules` selects some of the rules, and their signals and filters come with them. It replaces `--scanners` and `--strats`.
2. `enhanced_backtest.backtest()` creates a batch ID and calls `backtest_main` on a fresh event loop.
3. Connect to the database, which the momentum filter reads (see known issues). Create a `DataLoader(scale)` and a `Context(data_loader, trader, backtesting=True)`, and build the whole `StrategyGraph`. Don't record anything to algo run for now. Will figure out database at a later point.
4. Get the list of days. Equities use the Alpaca market calendar; crypto uses every calendar day.
5. For each day, step from the start of the day to the end, one minute or one day at a time. Each filter's universe holds the symbols of its latest run, which is on an earlier day when its recurrence is longer than a day. Rules keep evaluating the symbols they own even if no filter selects them. At each step `now`:
   1. Run any filters that are due with `run(now)`, and replace their universes with the symbols they select. A filter with no recurrence runs once per day.
   2. For symbols that just joined a universe, prefetch the day's bars, then prime each of their signals with `signal.get(symbol, day_end)`. Because `compute()` is causal, this computes the whole day at once, and later steps read from the cache.
   3. Evaluate the symbol rules exactly as the consumer does, with fired signals, ownership and open orders. Run each portfolio rule whose `recurrence` has elapsed.
   4. Fill the orders from the previous step at this bar's open: market orders always, and limit orders only if this bar trades through the limit. Apply the fees, update the rule's position and the symbol's owner, and call `rule.on_fill` with a `Trade`. Don't save `NewTrade` rows.
6. Write the results to files named by batch ID: `<batch_id>-trades.csv`, with one row per fill (time, rule, symbol, side, quantity, price, fee), and `<batch_id>-summary.txt`, with each rule's profit and number of trades. `backtest_main` also returns the trades as a DataFrame, so the optimizer can score the run.

## `optimizer [--concurrency=N]`

1. Load the trade plan, which must have an `[optimizer]` section with dates, `hyperparameters` and `parameters`.
2. Build an iterator over every hyperparameter combination. Also build the `Parameter`s, which get new values for every run (for example, a new portfolio).
3. For each combination: copy the trade plan, write the values into their `filters.<name>.<param>`, `signals.<name>.<param>` or `rules.<name>.<param>` paths (previously `strategies.<name>.<param>`), and start a `backtest_iteration` process.
4. Each process runs `backtest_main` (daily steps, US equities, no fees). If it succeeds, it saves an `OptimizerRun` row linking the session, the batch ID, the hyperparameter values and a score computed from the returned trades, since the trades are no longer in `NewTrade`.
5. Processes run in batches: start N, wait for all N to finish, then start the next N.

## `liu`

- **`liu quickstart`** is an interactive setup wizard:
  1. It asks whether you have an Alpaca account, and exits if `APCA_API_KEY_ID` or `APCA_API_SECRET_KEY` isn't set.
  2. It shows where the database is: SQLite by default, or Postgres if `DSN` is set.
  3. It lets you choose a folder for the samples.
  4. It runs the Alembic `upgrade_schema()`, downloads the sample trade plan and strategies from GitHub, and prints next steps. The samples use the old `[strategies]` format and need to be replaced with filter, signal and rule samples.
- **`liu create portfolio <amount> [--credit=X]`** checks the amounts are positive, calls `Portfolio.save` with a new UUID, and prints the ID.

## `portfolio <cmd>` (a Fire CLI)

- `create <size> <credit> <asset_type>`: saves a new portfolio.
- `list`: shows a table of all portfolios.
- `equity <id>`: shows current holdings with quantity and price.
- `account <id>`: shows cash transactions.
- `trades <id>`: shows the trade log.
- `recalc <id>`: resets the account balance to its starting size, deletes its transactions, and replays every trade as a cash transaction (buys negative, sells positive).

`equity`, `trades` and `recalc` read `NewTrade`, so they show nothing new unless live trading keeps recording trades.

## Known issues to fix

- **`backtester` ignores `TRADEPLAN_DIR`:** it loads the trade plan from that folder, then reloads `tradeplan.toml` from the current directory at `liualgotrader/scripts/backtester.py:146`.
- **Unused code in `producer.py`:** `trade_run` is never called, and at startup `run()` subscribes to a symbol list that is still empty. Neither causes a problem.
- **Open orders don't stop strategies:** `order_inflight` always returns `None`, so `handle_aggregate` (`liualgotrader/consumer.py:1222`) runs the strategies on a symbol even while it has an open order. The new consumer flow skips rules with open orders explicitly.
- **`DataLoader` time slices can look ahead:** a slice ends at the *nearest* bar, so `data_loader[symbol][start:now]` returns the bar after `now` when the bar at `now` is missing. `Context.bars` trims the result. Other code shouldn't slice by time without trimming.
- **Backtest fills are optimistic:** today's backtester fills at the close of the bar that the strategy just used to decide. The new flow fills at the next bar's open.
- **Momentum can only replay live picks:** in a backtest, the momentum scanner returns the `TrendingTicker` rows for its name instead of computing picks from history. So it only covers days the live trader ran. Also, the producer never sets `scanner_name`, so every row gets the column default `"momentum"`. A filter named `momentum1` would find nothing unless the producer saves the filter name.
- **Example trade plan doesn't load:** `examples/tradeplan.toml` sets `min_gap`, but the momentum scanner requires `today_change_percent`, so it exits on a `KeyError`.

## Notes

- The Indicator class computes data lazily as needed and its results are memoized as with signal.
- I want to limit the number of global variables defined at the base level in files by having per-process classes instantiated as part of the process's runtime, or in the case of signals, rules and indicators, by memoizing values as static class variables.
  - The draft uses the first approach for everything: one `Context` per run holds the shared indicators and caches, instead of static class variables. Static class dicts are process globals under another name. They would carry over between backtests in the same process (tests, in-process optimizer runs) unless something clears them, and an `__instances` dict on `Rule` would make two rules with the same settings share positions.

## Open questions

- **Recording live trades.** The old consumer saved a `NewTrade` row for each order and fill, linked to an `AlgoRun`. Without it, the portfolio commands go stale. A restart also loses track of which rule owns which position: broker positions come back with no owner, so no rule exits them. A rule name could replace `AlgoRun.strategy_name`.
- **Symbols already held.** At startup, symbols with open positions aren't subscribed unless a filter selects them again. One option is a built-in filter that returns the broker's open positions. `TraderAPI` has no method that lists positions yet.
- **Portfolio rules across consumers.** `PortfolioRule` answers how whole-portfolio strategies fit: the rule reads the latest signal values for all its symbols on a timer. But a symbol lives on one consumer, so that ownership stays inside one process. If a non-portfolio filter selects a symbol first, it's assigned to another consumer, and the portfolio rule on consumer 0 never sees it. The producer should at least log a warning. Alternatives: run one consumer when the plan has portfolio rules, or let consumer 0 fetch those bars itself on each recurrence. The old `run_all` had the same problem, because each consumer passed only its own symbols.
- **End-of-day liquidation.** `market_liquidation_end_time_minutes` is read into `config` but nothing uses it. Either rules handle it in `decide` (it's called every bar while they hold a position), or the runtime sends closing orders for day-trading rules.
- **Choosing a consumer.** "Fewest symbols" balances the number of symbols, not message volume. A hash of the symbol would make assignments repeatable between runs.
