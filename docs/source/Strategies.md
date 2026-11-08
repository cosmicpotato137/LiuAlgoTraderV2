(Strategies)=

# Strategies

Developing a Strategy is core for using `LiuAlgoTrader` framework.

A strategy is not a single class. The trade plan wires four kinds of
component into a strategy graph: filters select the symbols to trade,
indicators compute values from market data, signals turn indicator values
into predictions of price movement, and rules turn signals and positions
into orders. The base classes are in [liualgotrader.strategy.new_base](https://github.com/amor71/LiuAlgoTrader/blob/master/liualgotrader/strategy/new_base.py).

## Assumptions
This section assumes the audience has:

1. Carefully read and understood the `Concepts` section,
2. Read the `Filters` section and has a working setup of the framework with at least one Filter.


## No Liability Disclaimer
Any example, or sample is provided for training purposes only.
You may choose to use it, modify it or completely
disregard it - `LiuAlgoTrader` and its authors bare
no responsibility to any possible loses from using
a filter, signal, rule, or any other part of `LiuAlgoTrader` (on the other hand, they also won't
share your profits, if there are any).


## The Basics

| Component        | Reads                            | Returns                              |
| ---------------- | -------------------------------- | ------------------------------------ |
| `Filter`         | the market at `now`              | symbols to watch                     |
| `Indicator`      | one symbol's bars through `now`  | DataFrame indexed by bar time        |
| `Signal`         | one symbol's indicators through `now` | float Series: the sign is the direction, the magnitude (up to 1) is the confidence, NaN means no prediction |
| `SymbolRule`     | its signal's value for one symbol, with `self.signal.at()`, and its strategy's position in it | `OrderRequest` list |
| `PortfolioRule`  | its signal's latest values for all its symbols, with `self.signal.latest()`, and its strategy's positions | `OrderRequest` list |

* Each strategy in the trade plan has its own unique name, which its filter, signal and rule share,
* `LiuAlgoTrader` supports both *long* and *short* positions: a strategy's position is negative when short,
* Rules never call the broker. They return `OrderRequest` objects, which the
  framework submits when trading and simulates when back-testing, so the same
  rule runs unchanged in both,
* A position in a symbol belongs to the strategy whose rule opened it until
  the position is flat again. Meanwhile, no other strategy's rule is asked to
  decide on that symbol,
* A `SymbolRule` acts on a single symbol at a time, while a `PortfolioRule`
  acts on a collection of symbols (e.g. SP500), for rebalancing and other
  decisions that compare symbols.

### Time
Times are time zone-aware `pd.Timestamp` values in New York time. The `now`
passed to a component is the timestamp of the latest completed bar, and a
component must not read data stamped after it. `self.ctx.bars(symbol, start,
now)` returns a symbol's bars from `start` through `now`, and never a bar
stamped after `now`, even when back-testing.

### Context
Each run (a consumer process, the filter process or a back-test) creates one
`Context` and passes it to every component, as `self.ctx`. It holds:

* `data_loader`: the `DataLoader` of market data,
* `trader`: the broker, for read-only queries, or `None`,
* `backtesting`: whether the run is a back-test,
* `bars()`: the bars of a symbol from a start time through `now`,
* `is_shortable()`: whether a symbol can be sold short; the answer is cached per symbol, and always `True` when back-testing.

## Configuration
A trade plan is a folder of *strategy files*: the `TRADEPLAN_DIR` folder, or
the current folder if `TRADEPLAN_DIR` is not set. Each strategy file is a TOML
file that describes one strategy completely. The framework reads every
`*.toml` file in the folder, in file name order, so the folder should hold
strategy files only (not a `pyproject.toml`, for example).

A strategy file has a `name`, and a `[filter]`, a `[signal]` and a `[rule]`
table:

* `name` names the strategy, and its filter, signal and rule too. It is
  unique within the trade plan,
* the filter selects the symbols that the signal evaluates, and the rule
  decides on the signal. A filter, its signal and its rule make a
  *strategy*, and serve no other strategy,
* indicators are not in the trade plan: a signal creates the ones it needs.

The framework activates and deactivates strategies as a whole, and a strategy
owns the symbols it trades.

In each table, `class` names the class. With a `filename`, `class` is the name
of a class in that file. Without one, it is a dotted import path such as
`liualgotrader.filters.momentum.Momentum`. Each file is loaded once, and a
class that cannot be loaded raises an exception.

Every other setting of a table is passed to the class's `__init__()` as a
keyword argument, so a misspelled setting raises `TypeError` instead of being
ignored. `recurrence` is in minutes, and a `PortfolioRule` must have one.

The `trader`, `backtester` and `optimizer` raise a `ValueError` at startup,
naming the file, if a strategy file has a top-level setting other than
`name`, `filter`, `signal`, `rule` and `optimizer`, if its `name` is not a
non-empty string, or if its filter, signal or rule is not a table with a
`class`. They also raise a `ValueError` if two strategy files have the same
`name`, and log an error and exit if the folder has no TOML file. The
optional `[optimizer]` table is read by the `optimizer` only (see the
`Additional apps` section).

For example, a trade plan folder with two strategy files, `breakout_long.toml`:

```toml
name = "breakout_long"

[filter]
class = "liualgotrader.filters.momentum.Momentum"
min_volume = 30000
today_change_percent = 3.5
min_last_dv = 500000
max_share_price = 20.0
min_share_price = 2.0
from_market_open = 15
recurrence = 5

[signal]
class = "MySignal"
filename = "/home/liu/strategies/my_strategy.py"

[rule]
class = "MyRule"
filename = "/home/liu/strategies/my_strategy.py"
risk = 0.001
```

and `rebalance.toml`:

```toml
name = "rebalance"

[filter]
class = "MyWatchlist"
filename = "/home/liu/strategies/my_strategy.py"

[signal]
class = "MyTrend"
filename = "/home/liu/strategies/my_strategy.py"

[rule]
class = "MyRebalance"
filename = "/home/liu/strategies/my_strategy.py"
recurrence = 5
```

The example has two strategies: `breakout_long`, whose rule decides on the
symbols that the momentum filter selects, and `rebalance`, whose portfolio
rule decides on the symbols of a watchlist.

Position sizing, such as a portfolio value or risk per trade, belongs to the
rules, as rule settings.

## Developing Components

To inherit from the base classes:

```python
from liualgotrader.strategy.new_base import (Filter, Indicator,
                                             OrderRequest, PortfolioRule,
                                             Signal, SymbolRule)
```

Every component takes its trade plan settings as keyword arguments and passes
the remaining keyword arguments on to the base-class initializer, which sets
`self.ctx` and `self.name`:

```python
def __init__(self, window: int = 20, **kwargs):
    super().__init__(**kwargs)
    self.window = window
```

See the `Filters` section for developing filters.

### Indicators
An indicator implements `compute()`, which returns a DataFrame indexed by bar
timestamp for a symbol through `now`. `compute()` must be causal: the value of
each row may depend only on data stamped at or before that row, so that
computing through a later time yields the same earlier rows. The back-tester
relies on this to compute a whole day at once.

```python
class SMA(Indicator):
    def __init__(self, window: int = 20, **kwargs):
        super().__init__(**kwargs)
        self.window = window

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
        bars = self.ctx.bars(symbol, now - pd.Timedelta(days=5), now)
        return bars[["close"]].rolling(self.window).mean()
```

Signals and other indicators get an indicator with `create()`, which returns
one shared instance per context, class and parameters, so each indicator is
computed once per symbol whichever signals use it:

```python
sma = SMA.create(self.ctx, window=20)
values = sma.get(symbol, now)
```

`get()` returns the cached values, and computes them again only when the cache
does not cover `now` or the symbol's bars changed.

### Signals
A signal creates its indicators in its initializer, and implements
`compute()`, which returns a float Series indexed by bar timestamp. A positive
value predicts a rise and a negative value a fall, and the magnitude, at most
1, is the confidence. NaN means no prediction. A row with a value is an event
that the framework passes to the signal's rule, so a signal that holds a value
on every bar makes its rule decide on every bar. Like indicators,
signals must be causal and are cached. A signal does not know about positions
or orders.

```python
class AboveSMA(Signal):
    def __init__(self, window: int = 20, **kwargs):
        super().__init__(**kwargs)
        self.sma = SMA.create(self.ctx, window=window)

    def compute(self, symbol: str, now: pd.Timestamp) -> pd.Series:
        close = self.ctx.bars(symbol, now - pd.Timedelta(days=5), now).close
        sma = self.sma.get(symbol, now).close
        crossed = (close > sma) & (close.shift() <= sma.shift())
        return crossed.astype(float).where(crossed)
```

`signal.at(symbol, now)` returns the value stamped `now`, or NaN.

### Order requests
Rules return a list of `OrderRequest` objects:

```python
from liualgotrader.common.types import Order, OrderType

OrderRequest(symbol, Order.FillSide.buy, qty=10)
```

--> Purchase 10 shares at market,

```python
OrderRequest(
    symbol,
    Order.FillSide.buy,
    qty=10,
    type=OrderType.LIMIT,
    limit_price=4.4,
)
```

--> Requesting the framework to execute a limit order for quantity 10 and limit price $4.4. Similarly for the **sell** side.

The quantity must be positive, the type is `OrderType.MARKET` (the default) or
`OrderType.LIMIT`, and `limit_price` is set for limit orders only; otherwise
`OrderRequest` raises `ValueError`. Orders are day orders, and within one step
the framework submits sells before buys. Return an empty list to take no
action.

### Symbol rules
A `SymbolRule` implements `decide()`:

```python
async def decide(
    self,
    symbol: str,
    now: pd.Timestamp,
    position: float,
) -> list[OrderRequest]:
```

The framework calls `decide()` once per bar for each symbol that the
strategy's filter selected and on which the rule's signal fired, or in which
the strategy holds a position, so the rule can also exit on stops, targets or
the time of day. The framework does not call `decide()`, nor evaluate the
signal, while the strategy has an open order for the symbol, while another
strategy owns the symbol, or once the strategy is deactivated.

A rule reaches its signal as `self.signal`, and reads the signal's value
itself:

```python
value = self.signal.at(symbol, now)
```

`self.signal.at(symbol, now)` returns the value stamped `now`, which is NaN
unless the signal fired. For a symbol that the strategy holds, it returns
the signal's value even if the filter no longer selects the symbol.
`self.signal.fired(symbol, now)` returns whether the value is not NaN, and
treats an exception that the signal raises, which it logs, as not firing. To
read earlier values, use `self.signal.get(symbol, now)`.

### Portfolio rules
A `PortfolioRule` takes a `recurrence`, and implements `decide()`, which the
framework calls once per recurrence:

```python
async def decide(
    self,
    now: pd.Timestamp,
    positions: dict[str, float],
    symbols: list[str],
) -> list[OrderRequest]:
```

`positions` holds the strategy's position in each symbol it holds. `symbols`
holds, sorted, each symbol that the strategy's filter selected or that the
strategy holds. The rule reads the latest values of its signal itself:

```python
values = self.signal.latest(symbols, now)
```

`self.signal.latest(symbols, now)` returns a float Series indexed by symbol,
named after the signal: the latest value of the signal at or before `now` for
each symbol, and NaN where the signal has no value. An exception that the
signal raises for a symbol is logged, and the symbol's value is NaN.
When trading, the first consumer process runs every portfolio rule, and
receives every symbol of their filters.

### Symbol ownership
Strategies own symbols, not rules. A symbol belongs to at most one strategy
at a time: the strategy whose rule's order opened a position in it, until the
position is flat. A strategy may own many symbols.

A strategy whose rule requests an order for a symbol that another strategy
owns collides with it. By default the framework then deactivates the
strategy: it drops all of the rule's requests, sets the strategy's `active`
flag to `False`, and logs a warning. From then on the strategy's rule is not
asked to decide, its signal is not evaluated, and the symbols its filter
selects are ignored; in a back-test, its filter does not run. The strategy keeps the positions it holds, but nothing decides
on them again. Set `LIU_HALT_ON_COLLISION=1` to stop the run with an error
instead.

The filters of two strategies may select the same symbols, so the `symbols`
passed to a portfolio rule can include symbols that other strategies own. A
portfolio rule should not request every symbol in its list.

### Fills and cancellations
A rule hears about its own orders through two callbacks, which do nothing in
the base class:

* `on_fill(trade)` is called after a full or partial fill, once the framework
  updated the strategy's position. `trade` is an `OrderUpdate` from
  `liualgotrader.common.types`, with the side, quantity, price and fee of the
  execution,
* `on_cancel(order)` is called when an order is canceled, rejected or expires
  without a full fill, including when the framework cancels a stale order.

### Persisting state
Components keep their state in their own attributes, which last for the run.
To persist values across runs, for example for swing trading across batches,
use the key-value store in `liualgotrader.db.models.keystore`:

```python
from liualgotrader.db.models.keystore import KeyStore

await KeyStore.save("my_key", "my value")
value = await KeyStore.load("my_key")
```


## Example
Putting it all together in a momentum strategy, whose signal fires when a
fast simple moving average of the close crosses a slow one, and whose rule is
long from a bullish crossover to the next bearish one:

```{literalinclude} ../../examples/sma_crossover/strategy.py
:language: python
:linenos:
```

Sample strategy file, `sma_cross_long.toml`:

```{literalinclude} ../../examples/sma_crossover/sma_cross_long.toml
:language: toml
:linenos:
```



## Behind the scenes
Actually a lot is happening behind the scenes! The `trader` application
spawns consumer processes, a producer process and a filter process.
The number of consumer processes is either pre-determined by an environment
variable, or estimated based on the OS & hardware capabilities.

Each consumer process creates its `Context` and the strategies of the trade
plan. The producer assigns each symbol that a filter selects to one
consumer, and the assignment never changes. For each minute bar of a symbol,
the consumer:

1. skips each strategy that is inactive, has an open order for the symbol, or does not own the symbol while another strategy does,
2. gets the value of the signal of each other strategy whose filter selected the symbol; a value other than NaN means the signal fired,
3. calls `decide()` on the `SymbolRule` of each such strategy whose signal fired, and of the strategy that owns the symbol; the rule reads the signal's value with `self.signal.at()`,
4. submits the returned orders, sells before buys. The order that opens a position makes its strategy the symbol's owner.

When an order update arrives from the broker, the consumer updates the
strategy's position, releases the symbol once the position is flat, and calls the rule's
`on_fill()` or `on_cancel()`.

If an order is still open a minute after it was submitted, the framework
checks whether it was completed without a notification, and if so applies the
fill. Otherwise the order is cancelled, the rule's `on_cancel()` is called,
and the rule may re-trigger an operation based on signals.

The framework works behind the scenes to free the
strategy developer from worrying about broker
(Alpaca.Markets) and data provider (Polygon.io) integrations.

**Note**: live trades are not recorded in the `new_trades` table for now, and
positions held from an earlier session are not owned by any rule after a
restart.


## Additional Configurations

`LiuAlgoTrader` framework has quite a few knobs & levers to
configure the behaviour of the platform and the strategies.

The best place to check out all possibilities is [here](https://github.com/amor71/LiuAlgoTrader/blob/master/liualgotrader/common/config.py).

Some of the configurations are documented in the strategy files,
some are in environment variables, and some may be over-written by the
strategy developer.
