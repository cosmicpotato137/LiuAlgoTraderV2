(Filters)=

# Filters

As explained in the `Concepts` section, filters select stocks of interest from the stock universe.
Filters replace the scanners of earlier releases.
When the `trader` application starts, it reads the `tradeplan.toml` file and looks at the **[filters]** section to identify the filters to be instantiated and executed. The `trader` application exits with an error if the trade plan has no **[filters]** section. The framework comes with a generic momentum filter, but it is advised to use it as a reference for designing your own filters.

Each entry under **[filters]** is a filter instance: the table key is the instance name, and `class` names the class to instantiate. Two entries may use the same class with different settings. The `recurrence` setting is generic to all filters, and every other setting is passed to the class.

## No Liability Disclaimer
Any example, or sample is provided for training purposes only.
You may choose to use it, modify it or completely
disregard it - `LiuAlgoTrader` and its authors bare
no responsibility to any possible loses from using
a filter, signal, rule, or any other part of `LiuAlgoTrader` (on the other hand, they also won't
share your profits, if there are any).

## Developing a Filter

When developing your filter, you first need to import base-class `Filter`:

```python
from liualgotrader.strategy.new_base import Filter
```

Creating a filter involves:

1. Declare a class object that is inherited from base-class `Filter`,
2. Optionally overwrite the `__init__()` method, which is passed the configuration parameters from the `tradeplan.toml` file,
3. Overwrite the `run()` method, which is called when the framework is ready to execute the filter.

[base]: https://github.com/amor71/LiuAlgoTrader/blob/master/liualgotrader/strategy/new_base.py

### The `__init__()` function

A filter takes its trade plan settings as keyword arguments and passes the
remaining keyword arguments on to the base-class initializer, which sets
the run context (`self.ctx`), the instance name (`self.name`) and the
`recurrence`:

```python
def __init__(self, min_price: float = 2.0, **kwargs):
    super().__init__(**kwargs)
    self.min_price = min_price
```

A setting in the trade plan that the filter does not take raises `TypeError`,
so a misspelled setting is not silently ignored.

### The run() function

The `run()` method is at the heart of the Filter. The skeleton implementation:

```python
async def run(self, now: pd.Timestamp) -> list[str]:
```


The run() function returns a list of stock symbols which the framework needs to track. `now` is the time to select as of: the current time when trading, and a past time when back-testing, allowing developer to test various scenarios before deployment. Like every time in the framework, it is a time zone-aware `pd.Timestamp` in New York time. Use `self.ctx.backtesting` to tell the two apart.

The symbols a filter selects join its universe for the rest of the trading
day; a later run adds symbols but never removes them.

```python
self.ctx
```

Holds the `Context` of the run, with the services that components share:

* `self.ctx.data_loader`, the generic interface for querying market data,
* `self.ctx.trader`, the broker, for read-only queries such as the tradeable symbols (it may be `None`),
* `self.ctx.backtesting`, whether the run is a back-test.

### Using DataLoader() class

The DataLoader() class is core for writing filters (as well as signals and indicators). The class wraps on top of `pandas.DataFrame()` class which supports automatically downloading data.

For example, to load recent `ohlc` data for Apple Inc all you can do:

```python
apple_ohlc = self.ctx.data_loader['AAPL'][-1]
```

Notes:

1. Data will be loaded based on the time-scale (min/hour/day) configured by the LiuAlgoTrader framework. During trading you can expect per-minute time-scale, during back-testing you can select your desired time-frame,
2. Data is loaded from the data-providers configured in the `DATA_CONNECTOR` environment variable, the framework canonizes column names and guarantees to include at least open-high-low-close data, as well as volume. Different data providers may include additional details (such as VWAP, average, count and more),
3. Calling `self.ctx.data_loader['AAPL'].symbol_data` grants direct access to the `DataFrame` class,
4. Calling `self.ctx.data_loader.data_api` grants access to the instance of the `DataAPI` class, that provides an abstraction for the different data-providers. Using this class, the filter can get a market snapshot. For more details, check the implementation of the [momentum](https://github.com/amor71/LiuAlgoTrader/blob/master/liualgotrader/filters/momentum.py) filter.



### Behind the scenes
As a developer, I hate 'magic' that happens without my understanding, hence it's important for me to detail the inner workings of the framework. When trading, all filters run inside a dedicated process, with their own `Context`. When the process is executed, it creates the filters of the trade plan, and an `asyncio` task per filter. In fact, it's up to the filters to make sure they play along nicely and not starve each other with overly long calculations.

The filter task is to execute the `run()` method to determine a list of selected stocks and transmit them, with the filter name, over a Queue to the `producer` process. The task would then `sleep()` for the duration of the `recurrence` parameter (or just run once, if that parameter is not present).

Once the producer receives a selected symbol, it assigns it to a consumer process, registers it for events on the data-stream, and persists it in the database, with the filter name and the timestamp of receiving the selected stock. The producer then tells the symbol's consumer which filter selected it, so that the signals linked to that filter start evaluating the symbol. The built-in momentum filter uses the persisted picks when back-testing.

When back-testing, the `backtester` runs the filters itself, at each time step: a filter with a `recurrence` runs once that much time has elapsed, and a filter without one runs once per day.

### Example

An example of *filter.py*, from the SMA crossover example:

```{literalinclude} ../../examples/sma_crossover/filter.py
:language: python
:linenos:
```


Configuring a custom filter in the *tradeplan* TOML file is as easy as:

```none
[filters.my_filter]
class = "MyFilter"
filename = "examples/sma_crossover/filter.py"

symbols = ["AAPL", "MSFT"]
```

Upon execution, **trader** application will look for *filter.py* and
instantiate the `MyFilter` class with the arguments defined in the `tradeplan`
configuration file. A `class` without a `filename` is a dotted import path,
which is how the built-in filters are named.

### Linking filters to signals

A filter does not trade. Each signal in the trade plan lists the filters
whose symbols it evaluates, and a symbol selected by several filters reaches
the signals of each of them:

```none
[signals.breakout]
class = "MySignal"
filename = "my_signal.py"
filters = ["my_filter"]
```

See the `Strategies` section for signals and rules.



## Momentum Filter
Filters are defined in the *tradeplan.toml* TOML
configuration file under the section **[filters]**. Note that
several filters may run, at different schedules and
identify new stocks that needs to be fed into the strategy
pipeline.

The momentum filter is named by
`class = "liualgotrader.filters.momentum.Momentum"`, and
has several properties:

| Name                 | Description |
| -------------------- | ----------- |
| min_volume           | scan for tickers with minimal volume since day start |
| today_change_percent | minimum percentage change from the previous close (e.g. 3.5) |
| min_last_dv          | minimum last day dollar x volume |
| min_share_price      | minimum stock price |
| max_share_price      | maximum stock price |
| from_market_open     | number of minutes to wait, since market open before scanning for relevant stocks |
| max_symbols          | (optional) maximum number of symbols to scan for |
| recurrence           | (optional) minutes between re-runs of the filter, if not present, run only once a day |

For example:

```none
[filters.momentum1]
class = "liualgotrader.filters.momentum.Momentum"
min_volume = 30000
today_change_percent = 3.5
min_last_dv = 500000
max_share_price = 20.0
min_share_price = 2.0
from_market_open = 15
recurrence = 5
```

**Notes**

- Unless specified, the trader applications scans & trades a limited number of stocks, however that limitation can be overwritten by **LIU_MAX_SYMBOLS** env variable.
- When back-testing, the momentum filter does not compute picks from history: it returns the symbols that the `trader` application recorded for a filter of the same name on that day, so it only covers days on which the `trader` ran with that filter.
