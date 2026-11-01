"""Optimize trade plan hyperparameters by backtesting their combinations.

Usage: optimizer [--concurrency=<processes>]
Backtest each hyperparameter combination in the optimizer section of the
trade plan, tradeplan.toml in TRADEPLAN_DIR or the current directory, with
at most 4 concurrent backtests by default.

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
load_configuration
    Return the configuration loaded from a TOML file.
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

    Name each parameter by its dotted path in the trade plan, such as
    rules.<rule>.<name>.

    Parameters
    ----------
    parameters: Dict
        The configuration, with optional "filters", "signals" and "rules"
        sections that map each component to its parameter settings.
    """
    params = [
        Parameter(f"{section}.{component}.{name}", **settings)
        for section in ("filters", "signals", "rules")
        for component, component_params in parameters.get(section, {}).items()
        for name, settings in component_params.items()
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
    conf_dict: Dict,
    concurrency: int,
):
    """Run a backtest for each hyperparameter combination in parallel.

    Run each backtest in its own process. A portfolio parameter creates a new
    portfolio in the database for each backtest.

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
    conf_dict: Dict
        The trade plan to apply the values to.
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
                realize(realize(conf_dict, hyperparameter), parameters_values),  # type: ignore
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


def load_configuration(filename: str):
    """Return the configuration loaded from a TOML file.

    Exit the process if the file is not found.

    Parameters
    ----------
    filename: str
        The path of the file.
    """
    try:
        import toml

        conf_dict = toml.load(filename)
        logger.info("loaded configuration file from %s", filename)
    except FileNotFoundError:
        logger.error("could not locate tradeplan file %s", filename)
        sys.exit(0)

    return conf_dict


def main_cli() -> None:
    """Run the hyperparameter optimizer from the command line and exit.

    Run optimize with the optimizer section of the trade plan, taking an
    optional --concurrency option (default 4) for the number of parallel
    backtests. Exit early on invalid arguments, a missing optimizer section or
    unparsable dates.
    """
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Optimize trade plan hyperparameters by backtesting their combinations."
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
    fname = os.path.join(
        config.tradeplan_folder, config.configuration_filename
    )
    conf_dict = load_configuration(fname)

    if "optimizer" not in conf_dict:
        logger.error("optimizer directive not found in %s. aborting.", fname)
        sys.exit(0)

    logger.info("optimizer directive found in %s", fname)

    try:
        start_date = date_from_string(conf_dict["optimizer"]["start_date"])
        end_date = date_from_string(conf_dict["optimizer"]["end_date"])
    except Exception:
        logger.error("failed to load start & end dates")
        sys.exit(0)

    optimize(
        start_date=start_date,
        end_date=end_date,
        hyperparameters=create_hyperparameters(
            conf_dict["optimizer"]["hyperparameters"]
        ),
        parameters=create_parameters(conf_dict["optimizer"]["parameters"]),
        conf_dict=conf_dict,
        concurrency=concurrency,
    )

    sys.exit(0)
