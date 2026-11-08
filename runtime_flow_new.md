# Entry Points

The project has five console scripts, defined in `pyproject.toml`. All of them call `configure_logging()` first. The ones that trade load the trade plan with `load_tradeplan(config.tradeplan_folder)` (`liualgotrader/strategy/tradeplan.py`): every `*.toml` file in `TRADEPLAN_DIR`, or in the current directory if that isn't set, in file name order. Each file is a strategy file, which describes one strategy.

## Strategy components

A strategy is no longer one class. It's a `Strategy` (`liualgotrader/strategy/new_base.py`): one filter, one signal and one rule, which one strategy file describes. `create_strategies` returns the strategies of the trade plan as a dict by name. Signals create the indicators they need.

| Component | Reads | Returns | Runs in |
|---|---|---|---|
| `Filter` (replaces `Scanner`) | the market at `now` | symbols to watch | filter process (live), backtester |
| `Indicator` | one symbol's bars through `now` | DataFrame indexed by bar time | consumer, backtester |
| `Signal` | one symbol's indicators through `now` | float Series: the sign is the direction, the magnitude (up to 1) is the confidence, NaN means no prediction | consumer, backtester |
| `SymbolRule` | its signal's value for one symbol (`self.signal.at`), and its strategy's position in that symbol | `OrderRequest`s | consumer, backtester |
| `PortfolioRule` | its signal's latest values for all its symbols (`self.signal.latest`), and its strategy's positions | `OrderRequest`s | consumer 0 (live), backtester |

How the parts fit together:

- **Strategy files.** A strategy file has a `name` and a `[filter]`, a `[signal]` and a `[rule]` table. There are no links to configure: the signal evaluates the symbols that the filter of its file selects, and the rule decides on the signal of its file, so a filter, its signal and its rule make one strategy. The filter, signal and rule take the strategy's name, so `Component.name` is the strategy's name. `load_tradeplan` raises `ValueError`, naming the file, if a file isn't valid TOML, has a top-level key other than `name`, `filter`, `signal`, `rule` and `optimizer` (such as an old-format `filters`), has a `name` that isn't a non-empty string, or lacks one of the three tables or its `class` (`check_strategy`). It also raises `ValueError` if two files have the same `name`, and `FileNotFoundError` if the folder has no `*.toml` file, on which the scripts log an error and exit. The `trader`, `backtester` and `optimizer` load the trade plan before they start any process or backtest, and `create_strategies` checks it again (`check_tradeplan`). Indicators aren't in the trade plan: a signal creates the ones it needs with `Indicator.create(ctx, ...)`, which returns one shared instance for each class and set of parameters.
- **Context.** Each run creates one `Context`. A run is a consumer process, the filter process or a backtest. The context holds the `DataLoader`, an optional trader for read-only queries, the market calendar of the run's asset type (`ctx.calendar`, created on first use; US equities unless the run sets `asset_type`), the shared indicators and the cache versions. It replaces module globals and the class-level `__instances` and `__data` dicts, so a new backtest, test or optimizer iteration starts clean by creating a new context.
- **Time.** `now` is the timestamp of the latest completed bar. `compute()` in indicators and signals must be causal: each row can use only data stamped at or before it. `Context.bars()` never returns a bar stamped after `now`.
- **Memoization.** `Indicator.get` and `Signal.get` cache results for each symbol. A cached result is reused while it covers `now` and the symbol's bars haven't changed. The runtime calls `ctx.invalidate(symbol)` whenever it writes a bar. On a cache miss, results are computed through `ctx.horizon`, the latest bar the runtime has made available with `ctx.set_horizon()`: the consumer advances it to each minute bar, and the backtester to the end of each day, so a backtest computes each result once a day.
- **Orders.** Rules return `OrderRequest`s and never call the trader. The runtime submits them when trading live and simulates fills when backtesting, so the same rule runs unchanged in both. Within one step, the runtime submits sells before buys.
- **Ownership.** Strategies own symbols, not rules. A position in a symbol belongs to the strategy whose rule opened it until the position is flat, so a symbol has at most one owner and a strategy may own many symbols. Meanwhile, no other strategy's rule is asked to decide on that symbol. A rule isn't asked to decide on a symbol while its strategy has an open order for it. A rule hears about its orders through `on_fill` and `on_cancel`, which replace `buy_callback` and `sell_callback`.
- **Evaluation.** A signal is evaluated only for its own strategy. The runtime evaluates it, to tell whether it fired, only when the strategy is active, no other strategy owns the symbol, the strategy has no open order for the symbol, and its filter selected the symbol. A rule decides when its signal fired or its strategy owns the symbol. The rule reads the signal itself, with `self.signal.at(symbol, now)` or `self.signal.latest(symbols, now)`, so it also sees the signal's value for a symbol that its strategy holds and its filter no longer selects.
- **Collisions.** A strategy whose rule requests an order for a symbol that another strategy owns collides with it. In practice that's a portfolio rule, whose symbols can include symbols that another strategy's filter selected too, or a symbol rule that requests a symbol other than the one it was asked about. By default the runtime deactivates the strategy: it drops all of the rule's requests from that decision, sets the strategy's `active` flag to `False`, and logs a warning. The flag is the only one: since a strategy's filter, signal and rule serve no other strategy, it stops all three. The rule isn't asked to decide, the signal isn't evaluated and, in a backtest, the filter doesn't run. The filter process doesn't share the consumers' flags, so live it keeps running every filter, but the consumers ignore the results of the deactivated strategy's filter and drop its universe. The deactivated strategy keeps its positions, open orders and symbols, so fills still apply and no other strategy trades into a position it left open, but nothing decides on those positions again. With `LIU_HALT_ON_COLLISION=1`, a collision raises `OwnershipCollision` (`liualgotrader/common/exceptions.py`) instead: the backtest stops, and the trader stops all of its processes and exits with status 1. Which strategy wins depends on the order they decide in: in a step, symbol rules decide before portfolio rules, each in trade plan order.
- **Loading.** Every component table of a strategy file has a `class`. With a `filename`, `class` names a class in that file. Without one, it's a dotted import path, which is how built-ins like momentum are named. Each file is loaded once under its own module name, and load errors raise exceptions instead of calling `exit(0)`.

## Trade plan format

A trade plan is a folder of strategy files. Each `*.toml` file describes one strategy completely, and every TOML file in the folder is read, so the folder should hold only strategy files (not `pyproject.toml`, for example). `name` is unique within the trade plan. In each table, `class` names the class, which lets two strategies use the same class with different settings. Every setting not listed here is passed to the class's `__init__` as a keyword argument, so a misspelled setting raises `TypeError` instead of being ignored.

```toml
# breakout_long.toml

# the strategy's name, unique within the trade plan; its filter, signal and
# rule take it too
name = "breakout_long"

# the filter, which selects the symbols that the signal evaluates
[filter]
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

# the signal, which evaluates the symbols of the filter
[signal]
class = "MySignal"
filename = "examples/my_signal.py"
check_patterns = true

# the rule, which decides on the signal
[rule]
class = "MyBuy"
filename = "examples/my_rule.py"
# times of day, New York time
buy_window_start = "09:45"
buy_window_end = "15:30"
# position sizing belongs to the rule now
portfolio_value = 25000.0
risk = 0.001
```

```toml
# rebalance.toml: a second strategy has a file of its own
name = "rebalance"

[filter]
class = "MyWatchlist"
filename = "examples/my_filter.py"

[signal]
class = "MyTrend"
filename = "examples/my_signal.py"

# a PortfolioRule must have a recurrence, in minutes
[rule]
class = "MyRebalance"
filename = "examples/my_rule.py"
recurrence = 5
```

An optional `[optimizer]` table configures the optimizer for the strategy of its file; the other scripts ignore it.

## `trader`: live trading

`scripts/trader.py` starts several processes that pass messages through multiprocessing queues.

1. Set the process start method to `spawn`, create a batch ID (a UUID), and load the trade plan with `load_tradeplan`, which checks the strategy files and raises `ValueError` before any process starts. If the folder has no strategy file, log an error and exit.
2. Start N **consumer** processes, each with its own queue. Only consumer 0 runs portfolio rules.
3. Start one **producer** process. It gets every consumer queue plus a filter queue.
4. Start a **filter** process, which runs the filter of every strategy.
5. Wait until a consumer exits, which happens on Ctrl-C or when a consumer halts on a collision, then stop the other processes. Exit with status 1 if a consumer failed.

### Producer (`producer.py`)

1. Connect to the database and build the map that decides which consumer queue each symbol goes to. Find the *portfolio filters* with `portfolio_filters()`: the filters that feed a `PortfolioRule` through its signal, by strategy name. This loads the rule classes but doesn't create the rules.
2. Start the market-data stream (Alpaca, Polygon or Gemini, chosen by `DATA_CONNECTOR`).
3. Start the broker trader (chosen by `LIU_BROKER`). It subscribes to order updates and sends each one as a `trade_update` message to every consumer queue.
4. Loop on the filter queue. For each `{filter_name, symbols}`, where `filter_name` is the name of the filter's strategy:
   1. Assign each new symbol a consumer queue: consumer 0 for a portfolio filter, and otherwise the consumer with the fewest symbols. The assignment never changes. Subscribe the new symbols to second bars, minute bars and trades, and save them to `TrendingTicker` with their filter name.
   2. Send every consumer `{EV: "filter_result", symbols, filter_name}` with the symbols assigned to it, even when there are none, so that each consumer can replace the filter's universe. Already subscribed symbols are included, so that a symbol picked by a second filter reaches that filter's signal.

The producer no longer polls the `TradePlan` table or sends `new_strategy` messages.

### Filter process (`filters_runner.py`)

1. Create a `Context` with its own `DataLoader` and the broker trader, which the momentum filter asks for tradeable symbols. Create the filters with `create_filters()` (`liualgotrader/strategy/tradeplan.py`), each named after its strategy.
2. Run all filters at the same time. Each one calls `run(clock.now())`, puts a JSON object `{filter_name, symbols}` on the filter queue, even when it selects no symbols, then waits for its `recurrence`. A filter with no recurrence runs once.

### Consumer (`consumer.py`)

1. Create a `Context` with a `DataLoader` and the trader, and create the strategies, without their filters, with `create_strategies(tradeplan, ctx, with_filters=False)`. No loading from the database. Will rebuild later.
2. Keep the run state in one object created here, instead of the `trading_data` module globals: each filter's universe (the symbols of its latest run on this consumer), by strategy name, each strategy's positions, the open orders by order ID with the strategy that placed them, and the strategy that owns each symbol.
3. Run three tasks at the same time:
   - **Queue consumer:** handles each message by its `EV` with a `match` statement, and logs an error for an unknown type:
     - `trade_update`: looks up the open order by its ID, and ignores the update if this consumer has no such order, because updates go to every consumer. Otherwise it updates the strategy's position, releases the symbol if the position is now flat, and calls `rule.on_fill(trade)`. When the order is canceled, rejected or expires, it drops the open order and calls `rule.on_cancel(order)`.
     - `filter_result`: replaces the filter's universe with the symbols, as the backtester does.
     - Market data: adds the bar to the `DataLoader` and calls `ctx.invalidate(symbol)`. If the symbol has a stale open order, it checks the order and cancels it. Then, for a minute bar only (`AM`), with `now` set to the bar's timestamp:
       1. It skips each strategy that is inactive, has a `PortfolioRule`, has an open order for the symbol, or doesn't own the symbol while another strategy does.
       2. For each other strategy whose filter selected the symbol, it asks the strategy's signal whether it fired, with `signal.fired(symbol, now)`: whether `signal.at(symbol, now)` is not NaN.
       3. If the signal fired or the strategy owns the symbol, it calls `rule.decide(symbol, now, position)`. The rule reads the signal's value with `self.signal.at(symbol, now)`, NaN if it didn't fire.
       4. It submits the returned orders, sells before buys, and records each open order with its strategy. The order that opens a position makes its strategy the symbol's owner.
   - **Periodic runner** (consumer 0 only): runs the `PortfolioRule` of each strategy every `recurrence`, until the strategy is deactivated. It calls `rule.decide(now, positions, symbols)`, where `symbols` is the sorted list of every symbol in its filter's universe or its positions, and submits the orders, sells before buys. The rule reads the latest values of its signal with `self.signal.latest(symbols, now)`, a float Series indexed by symbol and NaN where the signal has no value. `latest` logs an exception that the signal raises for a symbol, and treats it as no value.
   - **Lingering-order check:** every 60 seconds while the market is open, checks open orders, cancels stale ones, and calls each canceled order's `rule.on_cancel`.

## `backtester from <date> [--to --scale --asset --*-fee-percentage]`

1. Parse the arguments and load the trade plan with `load_tradeplan`, raising `ValueError` if a strategy file isn't valid, or logging an error and exiting if the folder has no strategy file. `backtest()` logs and swallows exceptions, so the check comes first. The whole trade plan is back-tested; `--scanners` and `--strats` are gone.
2. `enhanced_backtest.backtest()` creates a batch ID and calls `backtest_main` on a fresh event loop.
3. Connect to the database, which the momentum filter reads (see known issues). Create a `DataLoader(scale)` and a `Context(data_loader, trader, backtesting=True, asset_type=asset_type)`, and create the strategies, with their filters, with `create_strategies()`. Don't record anything to algo run for now. Will figure out database at a later point.
4. Get the list of days from the context's calendar, `ctx.calendar`, which `market_calendar_factory(asset_type)` creates. Equities use the market calendar of the `CALENDAR_CONNECTOR` vendor (Alpaca by default); crypto uses every calendar day.
5. For each day, step from the start of the day to the end, one minute or one day at a time. Each filter's universe holds the symbols of its latest run, which is on an earlier day when its recurrence is longer than a day. Strategies keep deciding on the symbols they own even if no filter selects them. At each step `now`:
   1. Run the filters of the active strategies that are due with `run(now)`, and replace their universes with the symbols they select. A filter with no recurrence runs once per day.
   2. For symbols that just joined a universe, prefetch the day's bars, then prime each of their signals with `signal.get(symbol, day_end)`. Because `compute()` is causal, this computes the whole day at once, and later steps read from the cache.
   3. Evaluate the symbol rules exactly as the consumer does, with fired signals, ownership and open orders. Run the portfolio rule of each active strategy whose `recurrence` has elapsed.
   4. Fill the orders from the previous step at this bar's open: market orders always, and limit orders only if this bar trades through the limit. Apply the fees, update the strategy's position and the symbol's owner, and call `rule.on_fill` with an `OrderUpdate`. Don't save `Trade` rows.
6. Write the results to files named by batch ID: `<batch_id>-trades.csv`, with one row per fill (time, strategy, symbol, side, quantity, price, fee), and `<batch_id>-summary.txt`, with each strategy's profit and number of trades. `backtest_main` also returns the trades as a DataFrame, so the optimizer can score the run.

## `optimizer [--concurrency=N]`

1. Load the trade plan with `load_tradeplan`, raising `ValueError` before any backtest starts if a strategy file isn't valid. Find the strategy files that have an `[optimizer]` section with dates, `hyperparameters` and `parameters`. Log an error and exit if there are none, or if the dates of one don't parse.
2. Optimize each of these strategies in turn, with its own dates and its own optimizer session ID. Build an iterator over every hyperparameter combination. Also build the `Parameter`s, which get new values for every run (for example, a new portfolio).
3. For each combination: copy the strategy file, write the values into their `filter.<param>`, `signal.<param>` or `rule.<param>` paths, which `[optimizer.hyperparameters.rule]` and the like name relative to the strategy file (previously `rules.<name>.<param>` and the like), and start a `backtest_iteration` process. The process back-tests the strategy alone, not with the other strategies of the trade plan.
4. Each process runs `backtest_main` (daily steps, US equities, no fees). If it succeeds, it saves an `OptimizerRun` row linking the session, the batch ID, the hyperparameter values and a score computed from the returned trades, since the trades are no longer in `Trade`.
5. Processes run in batches: start N, wait for all N to finish, then start the next N.

## `liu`

- **`liu quickstart`** is an interactive setup wizard:
  1. It asks whether you have an Alpaca account, and exits if `APCA_API_KEY_ID` or `APCA_API_SECRET_KEY` isn't set.
  2. It shows where the database is: SQLite by default, or Postgres if `DSN` is set.
  3. It lets you choose a folder for the samples.
  4. It runs the Alembic `upgrade_schema()`, downloads the sample strategy file `momentum_long.toml` and its Python files from `examples/quickstart` on GitHub, and prints next steps.
- **`liu create portfolio <amount> [--credit=X]`** checks the amounts are positive, calls `Portfolio.save` with a new UUID, and prints the ID.

## `portfolio <cmd>` (a Fire CLI)

- `create <size> <credit> <asset_type>`: saves a new portfolio.
- `list`: shows a table of all portfolios.
- `equity <id>`: shows current holdings with quantity and price.
- `account <id>`: shows cash transactions.
- `trades <id>`: shows the trade log.
- `recalc <id>`: resets the account balance to its starting size, deletes its transactions, and replays every trade as a cash transaction (buys negative, sells positive).

`equity`, `trades` and `recalc` read `Trade`, so they show nothing new unless live trading keeps recording trades.

## Known issues to fix

- **Unused code in `producer.py`:** `trade_run` is never called, and at startup `run()` subscribes to a symbol list that is still empty. Neither causes a problem.
- **Open orders don't stop strategies:** `order_inflight` always returns `None`, so `handle_aggregate` (`liualgotrader/consumer.py:1222`) runs the strategies on a symbol even while it has an open order. The new consumer flow skips rules with open orders explicitly.
- **`DataLoader` time slices can look ahead:** a slice ends at the *nearest* bar, so `data_loader[symbol][start:now]` returns the bar after `now` when the bar at `now` is missing. `Context.bars` trims the result. Other code shouldn't slice by time without trimming.
- **Backtest fills are optimistic:** today's backtester fills at the close of the bar that the strategy just used to decide. The new flow fills at the next bar's open.
- **Momentum can only replay live picks:** in a backtest, the momentum filter returns the `TrendingTicker` rows saved under its name, which is its strategy's name, instead of computing picks from history. So it only covers days the live trader ran a strategy of that name.

## Notes

- The Indicator class computes data lazily as needed and its results are memoized as with signal.
- I want to limit the number of global variables defined at the base level in files by having per-process classes instantiated as part of the process's runtime, or in the case of signals, rules and indicators, by memoizing values as static class variables.
  - The draft uses the first approach for everything: one `Context` per run holds the shared indicators and caches, instead of static class variables. Static class dicts are process globals under another name. They would carry over between backtests in the same process (tests, in-process optimizer runs) unless something clears them, and an `__instances` dict on `Rule` would make two rules with the same settings share positions.

## Open questions

- **Recording live trades.** The old consumer saved a `Trade` row for each order and fill, linked to an `AlgoRun`. Without it, the portfolio commands go stale. A restart also loses track of which strategy owns which position: broker positions come back with no owner, so no strategy exits them. The strategy name could fill `AlgoRun.strategy_name`.
- **Symbols already held.** At startup, symbols with open positions aren't subscribed unless a filter selects them again. One option is a built-in filter that returns the broker's open positions. `TraderAPI` has no method that lists positions yet.
- **Portfolio rules across consumers.** `PortfolioRule` answers how whole-portfolio strategies fit: the rule reads the latest signal values for all its symbols on a timer. But a symbol lives on one consumer, so that ownership stays inside one process. If a non-portfolio filter selects a symbol first, it's assigned to another consumer, and the portfolio rule on consumer 0 never sees it. The producer should at least log a warning. Alternatives: run one consumer when the plan has portfolio rules, or let consumer 0 fetch those bars itself on each recurrence. The old `run_all` had the same problem, because each consumer passed only its own symbols.
- **End-of-day liquidation.** `market_liquidation_end_time_minutes` is read into `config` but nothing uses it. Either rules handle it in `decide` (it's called every bar while they hold a position), or the runtime sends closing orders for day-trading rules.
- **Choosing a consumer.** "Fewest symbols" balances the number of symbols, not message volume. A hash of the symbol would make assignments repeatable between runs.
