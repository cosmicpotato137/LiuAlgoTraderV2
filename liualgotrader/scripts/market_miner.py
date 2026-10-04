"""Off-hours calculations and data collection.

Usage: market_miner
Run it in the directory that holds the miner configuration, miner.toml.

Functions
---------
motd
    Log the welcome banner.
main
    Load and validate the miners named in the configuration.
main_cli
    Run the market miner from the command line.
"""

import asyncio
import importlib.util
import logging
import os
import sys
from typing import Dict, List, Optional

import toml

from liualgotrader.common import config
from liualgotrader.common.concurrency import get_event_loop
from liualgotrader.common.log import configure_logging
from liualgotrader.db.session import create_db_connection
from liualgotrader.miners.base import Miner

logger = logging.getLogger(__name__)

# rom liualgotrader.miners.stock_cluster import StockCluster


def motd(filename: str, version: str) -> None:
    """Log the welcome banner and the database DSN.

    Parameters
    ----------
    filename: str
        The script file name.
    version: str
        The build label.
    """
    logger.info("+=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=+")
    logger.info("%s %s starting", filename, version)
    logger.info("+=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=+")
    logger.info("DSN: %s", config.dsn)
    logger.info("+=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=+")


async def main(conf_dict: Dict):
    """Load and validate the miner classes named in the configuration.

    Exit the process if a miner class does not inherit from Miner, and log any
    other loading error. The miners are not run.

    Parameters
    ----------
    conf_dict: Dict
        The miner configuration, with a "miners" section keyed by miner name.
    """
    task_list: List[Optional[asyncio.Task]] = []

    await create_db_connection()
    for miner in conf_dict["miners"]:
        try:
            if "filename" in conf_dict["miners"][miner]:
                spec = importlib.util.spec_from_file_location(
                    "module.name", conf_dict["miners"][miner]["filename"]
                )
                if not spec:
                    raise AssertionError(
                        f"could not load module {conf_dict['miners'][miner]['filename']}"
                    )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore
            else:
                module = importlib.import_module(
                    f"liualgotrader.miners.{miner}"
                )
            class_name = f"{miner[0].upper()}{miner[1:]}"
            miner_class = getattr(module, class_name)

            if not issubclass(miner_class, Miner):
                logger.error(
                    "Miner must inherit from class %s", Miner.__name__
                )
                exit(0)
        except Exception as e:
            logger.error("miner %s resulted in exception:`%s`", miner, e)


def main_cli() -> None:
    """Run the market miner from the command line.

    Load the miner configuration from the current directory and run main. Exit
    if the configuration file is not found.
    """
    configure_logging()
    filename = os.path.basename(__file__)
    motd(filename=filename, version=config.build_label)

    # load configuration
    logger.info(
        "loading configuration file from %s/%s",
        os.getcwd(),
        config.miner_configuration_filename,
    )
    try:
        conf_dict = toml.load(config.miner_configuration_filename)
    except FileNotFoundError:
        logger.error(
            "could not locate market_miner configuration file %s",
            config.miner_configuration_filename,
        )
        sys.exit(0)

    try:
        get_event_loop().close()
        asyncio.run(main(conf_dict))
    except KeyboardInterrupt:
        logger.info("market_miner.main() - Caught KeyboardInterrupt")
    except Exception as e:
        logger.exception(
            "market_miner.main() - exception of type %s with args %s",
            type(e).__name__,
            e.args,
        )

    logger.info("*** market_miner completed ***")
