"""Load trade plans, and create the strategies that they describe.

A trade plan is a folder of strategy files: TOML files that each describe one
strategy completely, for example:

    name = "sma_cross_long"

    [filter]
    class = "MyFilter"
    filename = "examples/sma_crossover/filter.py"
    symbols = ["AAPL", "MSFT"]

    [signal]
    class = "SmaCrossover"
    filename = "examples/sma_crossover/strategy.py"
    fast = 10

    [rule]
    class = "SmaCrossoverRule"
    filename = "examples/sma_crossover/strategy.py"
    qty = 10

The name, unique within the trade plan, names the strategy and its filter,
signal and rule. The class setting of each table names the component's class:
a class in the file at filename, or a dotted import path without a filename.
The other settings of a table are passed to the class, and recurrence
settings, of filters and portfolio rules, are in minutes. An optional
optimizer table configures the optimizer.

Attributes
----------
COMPONENTS
    The tables of a strategy file that describe its components.

Functions
---------
load_tradeplan
    Return the strategies of the trade plan in a folder.
check_strategy
    Check that a strategy file describes a strategy.
check_tradeplan
    Check the strategy files of a trade plan.
create_filters
    Create the filters of a trade plan.
portfolio_filters
    Return the filters that feed a portfolio rule.
create_strategies
    Create the strategies of a trade plan.
"""

import copy
import logging
from collections import Counter
from pathlib import Path
from typing import TypeVar

import pandas as pd
import toml

from liualgotrader.common.utils import load_class
from liualgotrader.strategy.new_base import (Component, Context, Filter,
                                             PortfolioRule, Rule, Signal,
                                             Strategy)

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=Component)

# The tables of a strategy file that describe its components.
COMPONENTS = ("filter", "signal", "rule")
_SETTINGS = {"name", *COMPONENTS, "optimizer"}


def load_tradeplan(folder: str) -> list[dict]:
    """Return the strategies of the trade plan in a folder.

    Read every TOML file in the folder, in file name order, as a strategy
    file, and log the names of the strategies.

    Parameters
    ----------
    folder: str
        The folder of the strategy files.

    Returns
    -------
    Return the strategy files, as parsed.

    Raises
    ------
    Raise FileNotFoundError if the folder has no TOML file, and ValueError if
    a file is not valid TOML or does not describe a strategy, naming the file,
    or if two files describe strategies of the same name.
    """
    paths = sorted(Path(folder).glob("*.toml"))
    if not paths:
        raise FileNotFoundError(f"no strategy files (*.toml) in {folder}")
    tradeplan = []
    for path in paths:
        try:
            spec = toml.load(path)
            validate_strategy(spec)
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from None
        tradeplan.append(spec)
    _validate_unique_names(tradeplan)
    logger.info(
        "loaded strategies %s from %s",
        [spec["name"] for spec in tradeplan],
        folder,
    )
    return tradeplan


def validate_strategy(spec: dict) -> None:
    """Check that a strategy file describes a strategy.

    Check the settings only, without loading the classes of the components.

    Parameters
    ----------
    spec: dict
        The strategy file, as parsed; it is not modified.

    Raises
    ------
    Raise ValueError if the file has a top-level setting other than name,
    filter, signal, rule and optimizer, if name is not a non-empty string, or
    if filter, signal or rule is not a table with a class.
    """
    unknown = sorted(set(spec) - _SETTINGS)
    if unknown:
        raise ValueError(
            f"unknown settings {unknown}; a strategy file sets name, filter, "
            "signal, rule and optionally optimizer"
        )
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"name must be a non-empty string, got {name!r}")
    for key in COMPONENTS:
        table = spec.get(key)
        if not isinstance(table, dict) or "class" not in table:
            raise ValueError(
                f"strategy {name} must have a [{key}] table with a class"
            )


def _validate_unique_names(tradeplan: list[dict]) -> None:
    """Raise ValueError if two strategies of a trade plan share a name."""
    names = Counter(spec["name"] for spec in tradeplan)
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        raise ValueError(f"strategy names must be unique, got {duplicates}")


def validate_tradeplan(tradeplan: list[dict]) -> None:
    """Check the strategy files of a trade plan.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files, as parsed; they are not modified.

    Raises
    ------
    Raise the exceptions of check_strategy, and ValueError if two strategies
    share a name.
    """
    for spec in tradeplan:
        validate_strategy(spec)
    _validate_unique_names(tradeplan)


def _create_component(base: type[C], spec: dict, **kwargs) -> C:
    """Return the component that a table of a strategy file describes.

    Parameters
    ----------
    base: type[C]
        The class that the component's class must inherit from.
    spec: dict
        The table; it is not modified.
    kwargs
        The arguments passed to the class along with the table's settings,
        such as ctx and name.
    """
    settings = copy.deepcopy(spec)
    component_class = load_class(base, settings)
    if "recurrence" in settings and issubclass(
        component_class, (Filter, PortfolioRule)
    ):
        settings["recurrence"] = pd.Timedelta(minutes=settings["recurrence"])
    return component_class(**kwargs, **settings)


def create_filters(tradeplan: list[dict], ctx: Context) -> dict[str, Filter]:
    """Create the filters of a trade plan.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files, as parsed; they are not modified.
    ctx: Context
        The context passed to each filter.

    Returns
    -------
    Return the filter of each strategy, by strategy name, which is also the
    name of the filter.

    Raises
    ------
    Raise the exceptions of load_class.
    """
    return {
        spec["name"]: _create_component(
            Filter, spec["filter"], ctx=ctx, name=spec["name"]
        )
        for spec in tradeplan
    }


def portfolio_strategy_names(tradeplan: list[dict]) -> set[str]:
    """Return the strategy names that feed a PortfolioRule through its signal.

    Load the rule classes without creating the rules.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files, as parsed and checked; they are not modified.

    Returns
    -------
    Return the names of strategies with PortfolioRules.

    Raises
    ------
    Raise the exceptions of load_class.
    """
    return {
        spec["name"]
        for spec in tradeplan
        if issubclass(load_class(Rule, dict(spec["rule"])), PortfolioRule)
    }


def create_strategies(
    tradeplan: list[dict], ctx: Context, with_filters: bool = True
) -> dict[str, Strategy]:
    """Create the strategies of a trade plan.

    Name the filter, the signal and the rule of each strategy after it.

    Parameters
    ----------
    tradeplan: list[dict]
        The strategy files, as parsed; they are not modified.
    ctx: Context
        The context passed to each component.
    with_filters: bool, default True
        Whether to create the filters, which the live trader runs in a
        separate process.

    Returns
    -------
    Return the strategies by name, in the order of the trade plan.

    Raises
    ------
    Raise the exceptions of check_tradeplan and load_class.
    """
    validate_tradeplan(tradeplan)
    strategies = {}
    for spec in tradeplan:
        name = spec["name"]
        signal = _create_component(Signal, spec["signal"], ctx=ctx, name=name)
        rule = _create_component(Rule, spec["rule"], ctx=ctx, name=name, signal=signal)
        filter = (
            _create_component(Filter, spec["filter"], ctx=ctx, name=name)
            if with_filters
            else None
        )
        strategies[name] = Strategy(name, rule, filter)
    return strategies
