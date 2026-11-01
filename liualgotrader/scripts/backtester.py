"""Backtest the trade plan over a range of past days.

Usage: backtester from <start_date> [--asset=equity|crypto]
    [--rules=<name,...>] [--to=<end_date>] [--scale=day|minute]
    [--buy-fee-percentage=<percent>] [--sell-fee-percentage=<percent>]
Backtest the trade plan, tradeplan.toml, read from TRADEPLAN_DIR or else the
current directory. The defaults are equity, all rules, today, day and no
fees. --rules selects rules, and their signals and filters come with them.

Functions
---------
show_version
    Print the script file name and version.
dateFromString
    Return the date described by a natural-language string.
main_cli
    Run a backtest from the command line.
"""

import argparse
import logging
import os
import sys
from datetime import date

import parsedatetime.parsedatetime as pdt
import toml

from liualgotrader import enhanced_backtest
from liualgotrader.common import clock, config
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import AssetType, TimeScale

logger = logging.getLogger(__name__)

ASSET_TYPES = {"equity": AssetType.US_EQUITIES, "crypto": AssetType.CRYPTO}


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
    and exit. Exit with the usage text on missing or invalid arguments, and
    exit if the trade plan is not found.
    """
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Backtest the trade plan over a range of past days."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    from_parser = commands.add_parser(
        "from", help="backtest from a start date"
    )
    from_parser.add_argument(
        "start_date",
        type=dateFromString,
        help="first date, such as YYYY-MM-DD or 'yesterday'",
    )
    from_parser.add_argument(
        "--asset",
        type=str.lower,
        choices=ASSET_TYPES,
        default="equity",
        help="asset type being traded: equity = US Equities, crypto = Crypto-currency. Asset type affects the market schedule for backtesting",
    )
    from_parser.add_argument(
        "--rules",
        type=lambda rules: rules.split(","),
        help="comma-separated rules to backtest, with their signals and filters. DEFAULT is all rules",
    )
    from_parser.add_argument(
        "--to",
        dest="to_date",
        type=dateFromString,
        default=clock.today(),
        help="last date, such as YYYY-MM-DD. DEFAULT is today",
    )
    from_parser.add_argument(
        "--scale",
        choices=[scale.name for scale in TimeScale],
        default=TimeScale.day.name,
        help="time-scale for loading past data for back-test-ing",
    )
    from_parser.add_argument(
        "--buy-fee-percentage",
        type=float,
        default=0.0,
        help="Broker fees as percentage from transaction, from 0 to 100",
    )
    from_parser.add_argument(
        "--sell-fee-percentage",
        type=float,
        default=0.0,
        help="Broker fees as percentage from transaction, from 0 to 100",
    )
    args = parser.parse_args()
    logger.info("selected start date %s", args.start_date)

    config.filename = os.path.basename(__file__)

    fname = os.path.join(
        config.tradeplan_folder, config.configuration_filename
    )
    try:
        conf_dict = toml.load(fname)
        logger.info("loaded configuration file from %s", fname)
    except FileNotFoundError:
        logger.error("could not locate tradeplan file %s", fname)
        sys.exit(0)

    enhanced_backtest.backtest(
        from_date=args.start_date,
        to_date=args.to_date,
        scale=TimeScale[args.scale],
        config=conf_dict,
        rules=args.rules,
        asset_type=ASSET_TYPES[args.asset],
        buy_fee_percentage=args.buy_fee_percentage,
        sell_fee_percentage=args.sell_fee_percentage,
    )

    sys.exit(0)
