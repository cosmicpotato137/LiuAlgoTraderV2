"""Backtest the trade plan over a range of past days.

Usage: backtester from <start_date> [--asset=equity|crypto]
    [--rules=<name,...>] [--to=<end_date>] [--scale=day|minute]
    [--buy-fee-percentage=<percent>] [--sell-fee-percentage=<percent>]
Backtest the trade plan, tradeplan.toml, read from TRADEPLAN_DIR or else the
current directory. The defaults are equity, all rules, today, day and no
fees. --rules selects rules, and their signals and filters come with them.

Functions
---------
main_cli
    Run a backtest from the command line.
"""

import argparse
import logging
import os
import sys

import toml

from liualgotrader import enhanced_backtest
from liualgotrader.common import clock, config
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import AssetType, TimeScale
from liualgotrader.common.utils import date_from_string

logger = logging.getLogger(__name__)

ASSET_TYPES = {"equity": AssetType.US_EQUITIES, "crypto": AssetType.CRYPTO}


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
        type=date_from_string,
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
        type=date_from_string,
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
