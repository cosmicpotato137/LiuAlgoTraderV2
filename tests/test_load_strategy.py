import logging
import multiprocessing as mp
import re
import sys

import pytest
import toml

from liualgotrader import enhanced_backtest
from liualgotrader.common import config
from liualgotrader.scripts import backtester, optimizer, trader
from liualgotrader.strategy.base import (Context, Filter, Signal,
                                             SymbolRule)
from liualgotrader.strategy.tradeplan import (create_strategies,
                                              load_tradeplan,
                                              validate_tradeplan)

logger = logging.getLogger(__name__)

SCRIPTS = [
    pytest.param(script, argv, id=argv[0])
    for script, argv in (
        (trader, ["trader"]),
        (backtester, ["backtester", "from", "2024-01-01"]),
        (optimizer, ["optimizer"]),
    )
]


def strategy(name, **changes) -> dict:
    """Return a strategy file with the given name, and settings replaced or
    added."""
    return {
        "name": name,
        "filter": {"class": "F"},
        "signal": {"class": "S"},
        "rule": {"class": "R"},
        **changes,
    }


def without(key: str) -> dict:
    """Return a strategy file named a without the given setting."""
    spec = strategy("a")
    del spec[key]
    return spec


def write(folder, file_name: str, spec: dict) -> None:
    (folder / file_name).write_text(toml.dumps(spec))


def test_load_example_tradeplan():
    tradeplan = load_tradeplan("./examples/sma_crossover")
    strategies = create_strategies(tradeplan, Context(None))

    if list(strategies) != ["sma_cross_long"]:
        raise AssertionError(f"unexpected strategies {strategies}")
    s = strategies["sma_cross_long"]
    f = s.filter
    if not (
        isinstance(f, Filter)
        and isinstance(s.signal, Signal)
        and isinstance(s.rule, SymbolRule)
    ):
        raise AssertionError(f"unexpected components {f} {s.signal} {s.rule}")
    if {f.name, s.signal.name, s.rule.name} != {s.name}:
        raise AssertionError("components not named after their strategy")

    logger.info("Loaded strategies %s", list(strategies))


@pytest.mark.parametrize(
    "example, name",
    [
        ("optimizer", "trend_follow"),
        ("quickstart", "momentum_long"),
        ("sma_crossover", "sma_cross_long"),
    ],
)
def test_example_tradeplans_describe_one_strategy(example, name):
    tradeplan = load_tradeplan(f"./examples/{example}")
    if [spec["name"] for spec in tradeplan] != [name]:
        raise AssertionError(f"unexpected strategies {tradeplan}")


def test_valid_tradeplan_passes():
    validate_tradeplan([strategy("a"), strategy("b", optimizer={})])


@pytest.mark.parametrize(
    "plan, error",
    [
        pytest.param(
            [strategy("a", filters={})],
            "unknown settings ['filters']",
            id="unknown setting",
        ),
        pytest.param(
            [without("name")],
            "name must be a non-empty string, got None",
            id="no name",
        ),
        pytest.param(
            [strategy("")],
            "name must be a non-empty string, got ''",
            id="empty name",
        ),
        pytest.param(
            [strategy(1)],
            "name must be a non-empty string, got 1",
            id="name not a string",
        ),
        pytest.param(
            [without("signal")],
            "strategy a must have a [signal] table with a class",
            id="no signal",
        ),
        pytest.param(
            [strategy("a", rule={"qty": 1})],
            "strategy a must have a [rule] table with a class",
            id="rule without class",
        ),
        pytest.param(
            [strategy("a", filter="F")],
            "strategy a must have a [filter] table with a class",
            id="filter not a table",
        ),
        pytest.param(
            [strategy("a"), strategy("b"), strategy("a")],
            "strategy names must be unique, got ['a']",
            id="duplicate names",
        ),
    ],
)
def test_invalid_tradeplans_raise(plan, error):
    with pytest.raises(ValueError, match=re.escape(error)):
        validate_tradeplan(plan)


def test_create_strategies_checks_the_tradeplan():
    with pytest.raises(ValueError, match="strategy names must be unique"):
        create_strategies([strategy("a"), strategy("a")], Context(None))


def test_load_tradeplan_reads_toml_files_in_name_order(tmp_path):
    write(tmp_path, "b.toml", strategy("from_b"))
    write(tmp_path, "a.toml", strategy("from_a"))
    (tmp_path / "notes.txt").write_text("not a strategy")

    tradeplan = load_tradeplan(str(tmp_path))

    if tradeplan != [strategy("from_a"), strategy("from_b")]:
        raise AssertionError(f"unexpected trade plan {tradeplan}")


def test_load_tradeplan_raises_without_strategy_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="no strategy files"):
        load_tradeplan(str(tmp_path))


@pytest.mark.parametrize(
    "content, error",
    [
        (toml.dumps(strategy("a", rules={})), "unknown settings ['rules']"),
        ("name = ", ""),
    ],
    ids=["invalid strategy", "invalid TOML"],
)
def test_load_tradeplan_names_the_invalid_file(tmp_path, content, error):
    write(tmp_path, "a.toml", strategy("a"))
    (tmp_path / "b.toml").write_text(content)

    with pytest.raises(
        ValueError, match=re.escape(f"{tmp_path / 'b.toml'}: {error}")
    ):
        load_tradeplan(str(tmp_path))


def test_load_tradeplan_raises_on_names_shared_across_files(tmp_path):
    write(tmp_path, "a.toml", strategy("same"))
    write(tmp_path, "b.toml", strategy("same"))

    with pytest.raises(ValueError, match=re.escape("got ['same']")):
        load_tradeplan(str(tmp_path))


@pytest.fixture
def run_script(tmp_path, monkeypatch):
    """Return a function that runs a script on the trade plan in tmp_path,
    and fails if the script starts a process or a backtest."""
    monkeypatch.setattr(config, "tradeplan_folder", str(tmp_path))
    monkeypatch.setattr(config, "filename", "", raising=False)
    monkeypatch.setattr(mp, "set_start_method", lambda method: None)

    def start(*args, **kwargs):
        raise AssertionError("ran an invalid trade plan")

    monkeypatch.setattr(mp, "Process", start)
    monkeypatch.setattr(enhanced_backtest, "backtest", start)

    def run(script, argv):
        monkeypatch.setattr(sys, "argv", argv)
        # keep the log handlers of pytest
        monkeypatch.setattr(script, "configure_logging", lambda: None)
        script.main_cli()

    return run


@pytest.mark.parametrize("script, argv", SCRIPTS)
def test_scripts_raise_before_running_shared_names(
    script, argv, tmp_path, run_script
):
    write(tmp_path, "a.toml", strategy("same"))
    write(tmp_path, "b.toml", strategy("same"))

    with pytest.raises(ValueError, match="strategy names must be unique"):
        run_script(script, argv)


@pytest.mark.parametrize("script, argv", SCRIPTS)
def test_scripts_exit_without_strategy_files(script, argv, run_script):
    with pytest.raises(SystemExit):
        run_script(script, argv)


def test_optimizer_optimizes_each_strategy_alone(
    tmp_path, monkeypatch, run_script
):
    settings = {
        "start_date": "2024-01-01",
        "end_date": "2024-02-01",
        "parameters": {},
        "hyperparameters": {
            "rule": {"qty": {"param_type": "int", "min": 1, "max": 2}}
        },
    }
    write(tmp_path, "a.toml", strategy("plain"))
    write(tmp_path, "b.toml", strategy("tuned", optimizer=settings))
    runs = []
    monkeypatch.setattr(
        optimizer, "optimize", lambda **kwargs: runs.append(kwargs)
    )

    with pytest.raises(SystemExit):
        run_script(optimizer, ["optimizer"])

    if [run["strategy"]["name"] for run in runs] != ["tuned"]:
        raise AssertionError(f"unexpected optimizer runs {runs}")
    [qty] = runs[0]["hyperparameters"].hyperparameters
    if qty.name != "rule.qty":
        raise AssertionError(f"unexpected hyperparameter {qty.name}")
    realized = optimizer.realize(runs[0]["strategy"], ((qty.name, 2),))
    if realized["rule"] != {"class": "R", "qty": 2}:
        raise AssertionError(f"unexpected realized rule {realized['rule']}")
