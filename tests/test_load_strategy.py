import logging

import toml

from liualgotrader.strategy.new_base import (Context, Filter, Signal,
                                             StrategyGraph, SymbolRule)

logger = logging.getLogger(__name__)


def test_load_example_tradeplan():
    tradeplan = toml.load("./examples/sma_crossover/tradeplan.toml")
    graph = StrategyGraph.from_tradeplan(tradeplan, Context(None))

    if not all(isinstance(f, Filter) for f in graph.filters.values()):
        raise AssertionError(f"unexpected filters {graph.filters}")
    if not all(isinstance(s, Signal) for s in graph.signals.values()):
        raise AssertionError(f"unexpected signals {graph.signals}")
    if not all(isinstance(r, SymbolRule) for r in graph.rules.values()):
        raise AssertionError(f"unexpected rules {graph.rules}")
    for name in graph.rules:
        if not graph.rules_of_signal(graph.rule_signals[name][0]):
            raise AssertionError(f"rule {name} not linked to its signal")

    logger.info("Loaded signals %s, rules %s", graph.signals, graph.rules)
