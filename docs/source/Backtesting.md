# **Back-testing**

This section describes LiuAlgoTrader back-testing capabilities.
The `backtester` command-line tool runs the filters, signals and
rules of a trade plan over past market data, and writes the
resulting trades to files for analysis.

## No Liability Disclaimer
LiuAlgoTrader is provided with sample filters and
out-of-the-box strategies. You may choose to use it,
modify it or completely disregard it - Regardless,
LiuAlgoTrader and its Authors bare no responsibility
to any possible loses from using LiuAlgoTrader,
or any of its derivatives (on the other hand, they
also won't share your profits, if there are any).

## Liu approach to back-testing

While the framework was designed for high-performance real-time trading
with dynamic filtering of the stock universe, the framework is equipped with
a full stack of back-testing features.

Rules never call the broker: they return order requests, which the `trader`
application submits to the broker, and the `backtester` application
simulates. The same filters, signals and rules therefore run unchanged in
both. Back-testing can be done on minute or daily resolution.

### Picking the right back-testing tools

Day-trading sessions run filters repeatedly, over the universe of
stocks, and select stocks for trading. Signals evaluate the selected
stocks and rules decide how to act upon them. Swing-trading on the other hand do not
act on second, or even minute resolutions. Back-testing entire trading days,
minute by minute on the entire stock universe can be done, however it requires
downloading massive amounts of data, and computation power and is
not available out of the box with the provided momentum filter: when
back-testing, the momentum filter returns the stocks that the `trader`
application picked on that day. For more details
on how to customize filters to achieve such behavior, see the `Filters`
documentation page.

Perfecting a day-trading strategy can be done by running LiuAlgoTrader framework
on a paper-account, followed by back-testing the same days with revised
signals and rules. Such back-testing sessions allow improving strategies,
but are less effective on filters.

Swing-trading on selected stocks can be effectively done while back-testing
strategies over long period of data. Back-testing for Swing-trading is
avalaible out of the box, and does not require specialized filters or hardware.

### Word of caution

Day-trading is hard, perfecting day-trading algorithms is harder.
When back-testing day-trading sessions try to be aware of over-fitting and
**hindsight bias**. Make it a habit to always re-run strategy modifications
on a large number of day-trading sessions, and avoid making alterations
to fit to a specific less-successful trading day. The more you day-trade on a
paper-account, the more data you collect, which in turn make the back-testing
more effective. Last but not least, make small incremental changes, each time
on a single parameter and progress slowly.


## *backtester*

### Prerequisites
1. Installed and configured Liu Algo Trading Framework,
2. At least one strategy file, a TOML file that describes one strategy, in the `TRADEPLAN_DIR` folder, or in the current folder if `TRADEPLAN_DIR` is not set. For more details on how to write strategy files, see the `Configuration` and `Strategies` sections.

### How-To Use

To run the `backtester` application with no arguments type:

```bash
backtester
```

Displays the usage of the tool.

To run the back-testing you need to specify a starting day.
For example, assuming the strategy files are in the current folder:

```bash
backtester from '2020-10-18'
```

To back-test on minute bars:

```bash
backtester from '2020-10-18' --to='2020-10-23' --scale=minute
```

To back-test only some of the strategies, run the `backtester` with a trade
plan folder that holds only their strategy files. For example, to back-test
the SMA crossover example from the repository root:

```bash
TRADEPLAN_DIR=examples/sma_crossover backtester from 2024-01-01 --to=2024-12-31
```

Each back-test session creates a new `batch-id`, which the `backtester`
logs when it completes.

### How a back-test runs

For each day in the range (the market calendar for US equities, from the
vendor set by the `CALENDAR_CONNECTOR` environment variable, `alpaca` by
default, and every calendar day for crypto), the `backtester` clears the filters' selections,
then steps from the start of the day to its end, one minute or one day at a
time. At each step `now`:

1. The orders of the previous step are filled at the open of this bar: market orders always, and limit orders only if this bar trades through the limit. A limit order that is not filled is canceled after one bar, and its rule's `on_cancel()` is called. The fees are applied, the strategy's position is updated, and its rule's `on_fill()` is called,
2. The filters of the active strategies that are due run with `run(now)`: a filter with a `recurrence` once that much time has elapsed, and a filter without one once per day,
3. For the symbols that just got selected, the day's bars are loaded and the signals computed for the whole day at once (signals must be causal),
4. The symbol rules are evaluated exactly as the `trader` application does, with fired signals, ownership and open orders, and the portfolio rule of each active strategy whose `recurrence` has elapsed decides.

Strategies keep deciding on the symbols they own even if no filter selects
them on a later day.

### Results

The `backtester` writes two files to the current folder, named by the `batch-id`:

- `<batch_id>-trades.csv`, with one row per fill: the time, strategy, symbol, side, quantity, price and fee,
- `<batch_id>-summary.txt`, with each strategy's net cash flow, number of trades and open positions.

**Note**: back-tests do not write the `algo_run` and `new_trades` database tables, so the
analysis notebooks and the browser-based analyzer, which read those tables, do
not show new back-test sessions.

### Understanding command-line parameters

| Parameter Name      | Description |
| ------------------- | ----------- |
| to                  | The last day for calculating the back-testing. the date is provided in the format `YYYY-MM-DD`. The `to` date will be included in the back-testing session. If not specified, `today` is being used. |
| scale               | The time-scale for running the back-test. Allowed values are: day or minute. If not specified day will be used. Keep in mind that minute will take longer to run, but may be more realistic for your strategy. |
| asset               | The asset type being traded: equity (default) for US equities, or crypto. The asset type selects the market schedule for back-testing. |
| buy-fee-percentage  | trading fee for buying. Represented as percentage between 0 and 100. For example 0.3 is 0.3% transaction fee. |
| sell-fee-percentage | trading fee for selling. Represented as percentage between 0 and 100. For example 0.3 is 0.3% transaction fee. |

It is always recommanded to check the latest avaliable parameters by running

```bash
backtester
```

and seeing the full usage description.
