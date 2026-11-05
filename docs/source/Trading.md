# **Trading with Liu**

LiuAlgoTrader has two applications and a set of
analysis notebooks.

The applications are:

- *trader*
- *backtester*


This section describes the trader application,


## No Liability Disclaimer
LiuAlgoTrader is provided with sample filters and
out-of-the-box strategies. You may choose to use it,
modify it or completely disregard it - Regardless,
LiuAlgoTrader and its Authors bare no responsibility
to any possible loses from using LiuAlgoTrader,
or any of its derivatives (on the other hand, they
also won't share your profits, if there are any).


## *trader*

The trader application is the main application in
the LiuAlgoTrading package and it runs algorithmic
trading using the Alpaca Markets APIs.

### Prerequisites
1. Ensuring environment variables are properly set including Alpaca Market API credentials, and the database DSN when not using the default SQLite database,
2. At least one strategy file, a TOML file that describes one strategy, in the `TRADEPLAN_DIR` folder, or in the folder where the trader application is executed if `TRADEPLAN_DIR` is not set; the trader application exits with an error otherwise. For more details on how to write strategy files, see the `Configuration` and `Strategies` sections.

### Trading session
Each run of the `trader` application generates a unique
`batch-id`. The `batch-id` is displayed at the beginning
of the execution of the  `trader` application, as well
as at the end of the session.

The stocks that the filters pick during a trade session are
saved to the database with the `batch-id` and the filter name.
The built-in momentum filter uses them when back-testing the
same day.

The rules of the trade plan, defined in its strategy
files, decide on the picked stocks, and the `trader` application
submits their orders as day orders, sells before buys. A rule
hears about its orders through its `on_fill()` and `on_cancel()`
methods. See the `Strategies` section for more details.

**Note**: For now, live trades are not recorded in the
`new_trades` database table, and the positions of a rule are
kept in memory only. If a trading session is interrupted, the
positions held at the broker are not owned by any rule when
the `trader` application runs again, so no rule exits them.

### Usage

To run the trader app type:

```bash
trader
```

An expected beginning of execution should look like:

```{image} /images/trader-usage1.png
:width: 600
:align: left
:alt: '*trader* output'
```


### Understanding *trader* output and Logging

The *trader* application writes its log to STDOUT
(standard output) using the Python `logging` module.
Each entry is tagged with its time, process ID, level,
logger and function. Set the environment variable
`LIU_LOG_LEVEL` (for example `DEBUG` or `WARNING`) to
control how much is logged; the default is `INFO`.

The *trader* application uses a producer-consumers
design patterns. In other words, when executed a collection of
consumer processes will spawn, followed by a single producer process,
and a filter process which runs the filters according to the
specifications in the strategy files.
The first consumer process also runs every portfolio rule.
To understand the inner workings
read the `Concepts` section.

The *trader* application writes log outs in sections
to help troubleshooting and for better readability.

- The first section presents the filename being executed (`trader` in most cases) followed by a unique-id (GUID) which represents the trading session. Each time the `trader` application is run, a new batch-id will be created. To understand more read the `How to analyze your trades` section.
- The second section displays non-secure environment variables that may affect the trading behaviour. You should see the DSN (database connection string) properly displayed, and when you don't that's normally a sign that the env variables were not properly set.
- The third section displays the names of the strategies of the trade plan, and the folder of their strategy files. A basic validation of the strategy files is done during that point, and an error names the strategy file that is not valid.
- The fourth section normally displays the filter execution. For more details on filters read the `Filters` section.
- The fifth and last section displays the decisions of signals and rules, and their orders. For more details read the `Strategies` section.
