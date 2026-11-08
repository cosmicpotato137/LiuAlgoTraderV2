# Configuration

There are two parts of configuration for the **trader**
application: OS level environment variables,
and TOML strategy files read by the trader application.

## Environment variables

Environment variables are used to configure authentication
to external resources, such as the trading database,
broker access and more.

Authentication details should be kept separate from the rest
of the execution code & configuration to have better protection
as well as support dockerized executions.

Below is an example of the environment variables, which are not kept in the
repository:

```{literalinclude} ../../examples/.env.example
:language: bash
:linenos:
```

### Additional parameters

LiuAlgoTrader is a multi-processing framework with
producer-consumers design pattern. There is a
process for interacting with the data-stream
providers (e.g `Polygon.io`), a process for filtering
& picking stocks, and other processes specific to consumers.

The number of consumer processes depends on the number of CPU cores, load average and a
multiplication factor. The default multiplication
factor is **2.0** by default. However it is possible to
override this by the environment variable
`CPU_FACTOR`. If you notice that the load average
of your system is quite low when running the `trader`
application it's recommended to increase the number (depending on the complexity of your
strategies). If the load of the system is too high, it is recommended to lower the number.

It is also possible to by-pass `LiuAlgoTrader`
calculation of optimal number of processes, and
use a pre-defined number of consumer processes.
To do so you can assign a positive integer
to the environment variable `NUM_CONSUMERS`.

`TRADEPLAN_DIR` specifies the folder of the
trade plan's strategy files, by default the
current folder. It's used by the `trader`,
`backtester` and `optimizer` applications.

`DSN` holds the URL of the database, such as
`postgresql://user:password@host/db`. Leave it unset
for the SQLite database at `~/.liualgotrader/liu.db`.
See `Database Setup` in {doc}`(Advanced) Setup`.

`LIU_LOG_LEVEL` sets the minimum level of log
entries written to STDOUT by all `LiuAlgoTrader`
applications: `DEBUG`, `INFO` (default), `WARNING`
or `ERROR`.

`LIU_ENV` names the environment that algorithm
runs are recorded under in the `algo_run` table:
`PAPER` (default) or `LIVE`.

`LIU_REQUEST_ATTEMPTS` sets how many times a
request is sent when the Alpaca, Gemini or Tradier
API rejects it as rate-limited or unavailable,
such as with status 429 (default `6`), and
`LIU_REQUEST_RETRY_SECONDS` how many seconds to
wait between tries (default `10`). The Alpaca
Broker API waits until the time its response gives
for its rate limit to reset, if it gives one.

`LIU_HALT_ON_COLLISION` sets what happens when a
strategy requests a symbol that another strategy
owns: `0` (default) deactivates the strategy with
a warning, and `1` stops the `trader`,
`backtester` or `optimizer` run with an error.

## TOML strategy files
the **trader**, **backtester** & **optimizer** applications expect a trade plan:
a folder of TOML strategy files.
Click [here](https://toml.io/en/) to learn more on the TOML file format.

By default the applications read the trade plan from
the current folder, or from the `TRADEPLAN_DIR` folder
if it is set. They read every `*.toml` file in the folder,
in file name order, so the folder should hold strategy files
only. Each strategy file describes one strategy completely:
its `name`, which is unique within the trade plan,
the filter that selects stocks under **[filter]**,
the signal that evaluates the selected stocks under **[signal]**,
and the rule that turns the signal into orders under **[rule]**.
The filter, the signal and the rule take the name of the strategy.

The `class` setting of each table names the class to instantiate:
a dotted import path, or a class name together with the `filename`
of the Python file that defines it. Every other setting is
passed to the class, and a setting the class does not take raises
an error. `recurrence` settings are in minutes. A strategy file
with a top-level setting other than `name`, `filter`, `signal`,
`rule` and `optimizer`, without a `name`, or without one of the
three tables or their `class`, raises an error at startup, and so
do two strategy files with the same `name`. The optional
`[optimizer]` table is read by the `optimizer` application only.

Following is a sample strategy file.
See the Filters and Strategies sections respectively
to learn more on the available tools, and how to extend
them.

```{literalinclude} ../../examples/sma_crossover/sma_cross_long.toml
:language: toml
:linenos:
```
