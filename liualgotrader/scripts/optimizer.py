"""Optimize strategy hyperparameters by backtesting their combinations.

Usage: optimizer [--concurrency=<processes>]
For each strategy file of the trade plan, in TRADEPLAN_DIR or the current
directory, that has an optimizer section, backtest the strategy alone with
each hyperparameter combination of the section, with at most 4 concurrent
backtests by default.

Functions
---------
motd
    Log the welcome banner.
create_parameters
    Return the parameters defined in a configuration.
create_hyperparameters
    Return the hyperparameters defined in a configuration.
realize
    Return a copy of a configuration with parameter values applied.
optimize
    Run a backtest for each hyperparameter combination in parallel.
main_cli
    Run the hyperparameter optimizer from the command line and exit.
"""

import argparse
import copy
import logging
import multiprocessing as mp
import os
import sys
import uuid
from datetime import date
from typing import Dict, List

from liualgotrader.backtesting.optimizer import backtest_iteration
from liualgotrader.common import clock, config
from liualgotrader.common.hyperparameter import Hyperparameters, Parameter
from liualgotrader.common.log import configure_logging
from liualgotrader.common.utils import date_from_string
from liualgotrader.strategy.tradeplan import COMPONENTS, load_tradeplan

logger = logging.getLogger(__name__)


def motd(filename: str, version: str) -> None:
    """Log the welcome banner.

    Parameters
    ----------
    filename: str
        The script file name.
    version: str
        The build label.
    """
    logger.info("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    logger.info("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    logger.info("%s %s starting", filename, version)
    logger.info("----------------------------------------------------------")
    logger.info("----------------------------------------------------------")


def create_parameters(parameters: Dict) -> List[Parameter]:
    """Return the parameters defined in a parameter configuration.

    Name each parameter by its dotted path in the strategy file, such as
    rule.<name>.

    Parameters
    ----------
    parameters: Dict
        The configuration, with optional "filter", "signal" and "rule"
        sections that map each setting of the component to its parameter
        settings.
    """
    params = [
        Parameter(f"{section}.{name}", **settings)
        for section in COMPONENTS
        for name, settings in parameters.get(section, {}).items()
    ]

    logger.info("created %s parameters", len(params))
    return params


def create_hyperparameters(parameters: Dict) -> Hyperparameters:
    """Return the hyperparameters defined in a parameter configuration.

    Parameters
    ----------
    parameters: Dict
        The configuration, in the form accepted by create_parameters.
    """
    params = create_parameters(parameters)
    logger.info("created %s hyper-parameters", len(params))
    return Hyperparameters(params)


def realize(config: Dict, parameters: tuple) -> Dict:
    """Return a copy of a configuration with parameter values applied.

    Parameters
    ----------
    config: Dict
        The configuration; not modified.
    parameters: tuple
        Pairs of a dotted configuration path and its value.
    """
    d = copy.deepcopy(config)

    for parameter in parameters:
        name = parameter[0].split(".")

        element: Dict = d
        for i in name[:-1]:
            element = element[i]
        element[name[-1]] = parameter[1]

    return d


def optimize(
    start_date: date,
    end_date: date,
    hyperparameters: Hyperparameters,
    parameters: List[Parameter],
    strategy: Dict,
    concurrency: int,
):
    """Run a backtest of a strategy for each hyperparameter combination in
    parallel.

    Run each backtest in its own process, with the strategy alone. A
    portfolio parameter creates a new portfolio in the database for each
    backtest.

    Parameters
    ----------
    start_date: date
        The first day to backtest.
    end_date: date
        The last day to backtest.
    hyperparameters: Hyperparameters
        The hyperparameter combinations to test.
    parameters: List[Parameter]
        The parameters, such as portfolios, created anew for each backtest.
    strategy: Dict
        The strategy file to apply the values to.
    concurrency: int
        The maximum number of backtests to run at the same time.
    """
    optimizer_session_id = str(uuid.uuid4())
    logger.info(
        "-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-"
    )
    logger.info("optimizer session_id %s starting", optimizer_session_id)
    logger.info(
        "-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-"
    )

    processes = []
    for hyperparameter in iter(hyperparameters):
        parameters_values = (x() for x in parameters)
        p = mp.Process(
            target=backtest_iteration,
            args=(
                optimizer_session_id,
                start_date,
                end_date,
                [realize(realize(strategy, hyperparameter), parameters_values)],  # type: ignore
                hyperparameter,
            ),
        )
        processes.append(p)
        p.start()

        if len(processes) == concurrency:
            for p in processes:
                p.join()
            processes = []

    logger.info("done.")


def main_cli() -> None:
    """Run the hyperparameter optimizer from the command line and exit.

    Run optimize for each strategy with an optimizer section, taking an
    optional --concurrency option (default 4) for the number of parallel
    backtests. Exit early on invalid arguments, a missing trade plan, no
    optimizer section or unparsable dates.

    Raises
    ------
    Raise ValueError if a strategy file of the trade plan is not valid, see
    load_tradeplan.
    """
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Optimize strategy hyperparameters by backtesting their combinations."
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=4,
        help="maximum number of concurrent backtests. DEFAULT 4",
    )
    concurrency: int = parser.parse_args().concurrency

    mp.set_start_method("spawn")
    config.filename = os.path.basename(__file__)
    motd(filename=config.filename, version=config.build_label)
    logger.info("using concurrency %s", concurrency)
    try:
        tradeplan = load_tradeplan(config.tradeplan_folder)
    except FileNotFoundError as error:
        logger.error("could not locate the trade plan: %s", error)
        sys.exit(0)

    runs = []
    for strategy in tradeplan:
        if "optimizer" not in strategy:
            continue
        try:
            start_date = date_from_string(strategy["optimizer"]["start_date"])
            end_date = date_from_string(strategy["optimizer"]["end_date"])
        except Exception:
            logger.error(
                "failed to load start & end dates of %s", strategy["name"]
            )
            sys.exit(0)
        runs.append((strategy, start_date, end_date))

    if not runs:
        logger.error(
            "no strategy in %s has an optimizer directive. aborting.",
            config.tradeplan_folder,
        )
        sys.exit(0)

    for strategy, start_date, end_date in runs:
        logger.info("optimizing strategy %s", strategy["name"])
        optimize(
            start_date=start_date,
            end_date=end_date,
            hyperparameters=create_hyperparameters(
                strategy["optimizer"]["hyperparameters"]
            ),
            parameters=create_parameters(
                strategy["optimizer"]["parameters"]
            ),
            strategy=strategy,
            concurrency=concurrency,
        )

    sys.exit(0)
