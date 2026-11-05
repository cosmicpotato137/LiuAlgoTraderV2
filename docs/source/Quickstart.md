# **Quickstart**

## Prerequisite

1. Python 3.12 or later,

2. Paper, or a funded account with [Alpaca](https://alpaca.markets/docs/about-us) Markets.


## Touch & Go

**NOTE** for [Windows](https://liualgotrader-v2.readthedocs.io/en/latest/Troubleshooting.html#q-can-i-run-liu-on-windows) users

**Step 1**: install LiuAlgoTrader

```bash
pip install liualgotrader
```

Having issues on installation? Check out the installation [FAQ](https://liualgotrader-v2.readthedocs.io/en/latest/Troubleshooting.html)

**Step 2**: Run the setup wizard

```bash
liu quickstart
```

Follow the installation wizard instructions. The wizard checks your Alpaca
credentials, creates the database and downloads the samples:

```{image} /images/liu-wizard.png
:width: 800
:align: left
:alt: liu setup wizard
```


## First time use

LiuAlgoTrader `quickstart` wizard installs samples allowing a first-time experience of the framework. Follow the post-installation instructions, and try to back-test a specific day
from within the samples directory:

```bash
backtester from 2026-09-01
```

The backtester prints the batch-id of the session when it completes.

**NOTE**: the `backtester` reads every TOML file in the current
directory, or in `TRADEPLAN_DIR` if it is set, as a strategy file
(see the `Strategies` section).
A `tradeplan.toml` of earlier releases, such as one that an earlier
version of the wizard downloaded, makes it raise an error at startup.
Remove it, or use the samples in the `examples` folder of the GitHub
repository.

### `Voila!`
You should find your back-test session in two files in the current
directory: `<batch-id>-trades.csv`, with one row per trade, and
`<batch-id>-summary.txt`, with the results of each strategy.
You're all set now.

**NOTE**

Back-testing a whole day requires downloading market data for that day, which
may take minutes to an hour depending on your connection type.

## The Database

LiuAlgoTrader keeps its data, such as portfolios and the stocks picked by
filters, in a SQLite database at `~/.liualgotrader/liu.db`, and creates its
tables on first use. See
[Database Setup](https://liualgotrader-v2.readthedocs.io/en/latest/(Advanced)%20Setup.html#database-setup) for using a PostgreSQL server instead.

## What's Next?

Read through the rest of the documentation, starting with the 'Getting Started' section. Understand the framework concepts, create your own filters, signals and rules, and run a trading session.
