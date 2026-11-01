"""Backtest the trade plan over a range of past days.

Usage: backtester from <start_date> [--asset=equity|crypto]
    [--rules=<name,...>] [--to=<end_date>] [--scale=day|minute]
    [--buy-fee-percentage=<percent>] [--sell-fee-percentage=<percent>]
Backtest the trade plan, tradeplan.toml, read from TRADEPLAN_DIR or else the
current directory. The defaults are equity, all rules, today, day and no
fees. --rules selects rules, and their signals and filters come with them.

Functions
---------
show_usage
    Print the command-line usage and options of the backtester.
show_version
    Print the script file name and version.
dateFromString
    Return the date described by a natural-language string.
main_cli
    Run a backtest from the command line.
"""

import getopt
import logging
import os
import sys
from datetime import date
from typing import List, Optional

import parsedatetime.parsedatetime as pdt
import toml

from liualgotrader import enhanced_backtest
from liualgotrader.common import clock, config
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import AssetType, TimeScale

logger = logging.getLogger(__name__)


def show_usage():
    """Print the command-line usage and options of the backtester."""
    print(
        f"\n{sys.argv[0]} from <start_date> [--asset=equity(DEFAULT)|crypto] [--rules=<rule-name,>] [--to=<end_date> DEFAULT is today] [--scale=day(DEFAULT)|minute] [--buy-fee-percentage=0.(DEFAULT)] [--sell-fee-percentage=0.(DEFAULT)]",
    )

    print("\n\noptions:")
    print(
        "asset\t\t\tAsset type being traded. equity = US Equities, crypt = Crypto-currency. Asset type affects the market schedule for backtesting."
    )
    print(
        "to\t\t\tdate string in the format YYYY-MM-DD, if not provided current day is selected"
    )
    print("scale\t\t\ttime-scale for loading past data for back-test-ing")
    print(
        "rules\t\t\trules to back-test, with their signals and filters. DEFAULT is all rules"
    )
    print(
        "buy-fee-percentage\tBroker fees as percentage from transaction, from 0 to 100."
    )
    print(
        "sell-fee-percentage\tBroker fees as percentage from transaction, from 0 to 100."
    )


def show_version(filename: str, version: str) -> None:
    """Print the script file name and version.

    Parameters
    ----------
    filename: str
        The script file name.
    version: str
        The Git version label.
    """
    print(f"filename:{filename}\ngit version:{version}\n")


def dateFromString(s: str) -> date:
    """Return the date described by a natural-language string.

    Parameters
    ----------
    s: str
        The date string, either explicit or relative to the current New York
        time, such as "yesterday".

    Raises
    ------
    Raise ValueError if the string cannot be parsed as a date or a time.
    """
    c = pdt.Calendar()
    result, what = c.parse(s, clock.now().timetuple())
    dt = None

    # what was returned (see http://code-bear.com/code/parsedatetime/docs/)
    # 0 = failed to parse
    # 1 = date (with current time, as a struct_time)
    # 2 = time (with current date, as a struct_time)
    # 3 = datetime
    if what in (1, 2):
        # result is struct_time
        dt = date(*result[:3])
    elif what == 3:
        # result is a datetime
        dt = result.date()

    if dt is None:
        raise ValueError(f"Don't understand date '{s}'")

    return dt


def main_cli() -> None:
    """Run a backtest from the command line.

    Parse the from command and its options from sys.argv, run the backtest
    and exit. Print the usage text and exit on missing or invalid arguments,
    and exit if the trade plan is not found.
    """
    configure_logging()
    if len(sys.argv) == 1:
        show_usage()
        sys.exit(0)

    config.filename = os.path.basename(__file__)

    # TODO: simplify path operations across the repo by using join
    folder = (
        config.tradeplan_folder
        if config.tradeplan_folder[-1] == "/"
        else f"{config.tradeplan_folder}/"
    )
    fname = f"{folder}{config.configuration_filename}"
    try:
        conf_dict = toml.load(fname)
        logger.info("loaded configuration file from %s", fname)
    except FileNotFoundError:
        logger.error("could not locate tradeplan file %s", fname)
        sys.exit(0)

    if sys.argv[1] == "from":
        from_date = dateFromString(sys.argv[2])
        logger.info("selected %s applied %s", sys.argv[2], from_date)
        try:
            rules: Optional[List] = None
            to_date = clock.today()
            scale = TimeScale["day"]
            buy_fee_percentage = 0.0
            sell_fee_percentage = 0.0
            asset_type = AssetType.US_EQUITIES
            opts, args = getopt.getopt(
                sys.argv[3:],
                shortopts="",
                longopts=[
                    "to=",
                    "scale=",
                    "rules=",
                    "buy-fee-percentage=",
                    "sell-fee-percentage=",
                    "asset=",
                ],
            )
            # TODO: use argparse for argument handling across the repo
            # to simplify the entrypoints as much as possible
            for opt, arg in opts:
                if opt in ("--rules"):
                    rules = arg.split(",")
                elif opt in ("--to"):
                    to_date = dateFromString(arg)
                elif opt in ("--buy-fee-percentage"):
                    buy_fee_percentage = float(arg)
                elif opt in ("--sell-fee-percentage"):
                    sell_fee_percentage = float(arg)
                elif opt in ("--asset"):
                    if arg.lower() == "crypto":
                        asset_type = AssetType.CRYPTO
                    elif arg.lower() == "equity":
                        asset_type = AssetType.US_EQUITIES
                    else:
                        print(
                            f"ERROR: value {arg} not supported for parameter 'asset'"
                        )
                        sys.exit(0)
                elif opt in ("--scale"):
                    # TODO: define enum for all available timescales across the repo
                    if arg in ("day", "minute"):
                        scale = TimeScale[arg]
                    else:
                        print(
                            f"ERROR: wrong `scale` parameter {arg} passed: not implemented yet"
                        )
                        sys.exit(0)
        except getopt.GetoptError as e:
            print(f"Error parsing options:{e}\n")
            show_usage()
            sys.exit(0)

        enhanced_backtest.backtest(
            from_date=from_date,
            to_date=to_date,
            scale=scale,
            config=conf_dict,
            rules=rules,
            asset_type=asset_type,
            buy_fee_percentage=buy_fee_percentage,
            sell_fee_percentage=sell_fee_percentage,
        )
    else:
        print(f"Error parsing {sys.argv[1:]}\n")
        show_usage()
        sys.exit(0)

    sys.exit(0)
