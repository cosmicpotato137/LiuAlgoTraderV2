# Additional apps


## Optimizer

The `optimizer` application is a tool for back-testing strategy with different parameters in parallel.
`optimizer` helps select the best hyper-parameters for a strategy.

### How-To

To use the `optimizer` application, a new section should be added to the strategy file of the strategy to optimize:

```{literalinclude} ../../examples/optimizer/trend_follow.toml
:language: toml
:linenos:
```

* Note the [optimizer] section is added to the strategy file, with `parameters` and `hyperparameters` tables,
* `start_date` & `end_date` specify the time-window for back-testing,
* The `optimizer` always runs in daily time-scale, on US equities and without fees,
* Parameters and hyper-parameters are named by the table of the strategy file they apply to: `filter`, `signal` or `rule`. For example, `[optimizer.hyperparameters.rule]` lists the hyper-parameters of the strategy's rule, and `[optimizer.hyperparameters.signal]` those of its signal,
* The `optimizer` optimizes each strategy file of the trade plan that has an [optimizer] section, one strategy after the other, each with its own dates. It back-tests each strategy alone, without the other strategies of the trade plan.


### Parameters and Hyper-parameters

The `optimizer` application supports two different
types of configuration-space constructs: Parameters and Hyper-Parameters.

Parameters are meta-instructions for generating configurations for filters, signals and rules,
that are calculated per back-testing step. In contrast, Hyper-Parameters is a
configuration space spanning a product of all possible values for each Hyper-Parameter.

### Usage

To run the `optimizer` application, simply type:

```bash
optimizer
```

The application will read the strategy files of the trade plan, in the `TRADEPLAN_DIR` folder or the current folder, and spawn processes for back-testing the different configurations of each strategy that has an [optimizer] section. It logs an error and exits if no strategy file has one.

### Model
Each `optimizer` execution generates a UUID for each strategy that it optimizes, representing a unique execution identification.
Each back-test will generate its own `batch-id`.
The relationship between the optimizer execution id, batch-ids and the hyper-parameters configurations
is stored in the **OPTIMIZER_RUN** database table, together with the `score` of each back-test: its net cash flow.
Back-tests do not write their trades to the database, so compare configurations by their score, or by the
files that each back-test writes (see the `Back-testing` section).

### Analysis
A dedicated Jupyter Notebook (see the `analysis` section) allows loading and comparing
performance of different configurations. The notebook reads the trades from the database,
so it shows only optimizer sessions of earlier releases.

### Parallel execution
Similar to `trader` application, `optimizer` supports multi-processing execution to optimize run times. By default the `optimizer` executes 4 processes, however that may be changed by specifying the `--concurrency` parameter.


### Portfolio

The Portfolio app uses Google [Fire](https://github.com/google/python-fire) infrastructure for CLI development.


The application provides means to creating portfolios, summarizing current portfolio status in a neat table, displaying the cash account transactions, as well as a re-processing tool.

### Usage

To see the different commands of the `portfolio` application, type:

```bash
portfolio --help
```


### Create Portfolio

To create a new portfolio, type:

```bash
portfolio create <portfolio cash amount> <credit line>
```

For example, running the below creates a new portfolio, with a cash account of $10,000 and a credit line of $1,000.

```bash
portfolio create 10000 1000
```


### Re-processing

The cash account is updated with every trade. Normally, there will not be a need to re-calculate the cash requests from the account. In some cases, however, where manual intervention is required, it may be helpful to re-calculate the cash transaction.

**WARNING**: This operation is irreversible!

To create a recalculated portfolio, type:

```bash
portfolio recalc <portfolio-id>
```
