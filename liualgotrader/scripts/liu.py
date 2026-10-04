"""Command-line setup and administration of the Liu framework.

Usage: liu quickstart
       liu create portfolio <amount> [--credit=<credit>]
The quickstart command runs the setup wizard. The create portfolio command
creates a portfolio of a positive amount and optional positive credit line.

Functions
---------
show_version
    Print the name of the framework with its build label.
show_usage
    Print the version banner and the command-line usage of liu.
setup_db
    Create or upgrade the database schema.
setup_samples
    Download the quickstart samples.
quickstart
    Guide the user interactively through the initial setup.
create_account
    Create an account and print its identifier.
create_portfolio
    Create a portfolio and print its identifier.
main_cli
    Run the liu command-line interface and exit.
"""

import getopt
import os
import pathlib
import sys
import uuid

import requests

from liualgotrader.common import config
from liualgotrader.common.concurrency import get_event_loop
from liualgotrader.common.log import configure_logging
from liualgotrader.db.models.accounts import Account
from liualgotrader.db.models.portfolio import Portfolio
from liualgotrader.db.session import (create_db_connection, database_url,
                                      upgrade_schema)


def show_version():
    """Print the name of the framework together with its build label."""
    print(f"Liu Algo Trading Framework v{config.build_label}")


def show_usage():
    """Print the version banner and the command-line usage of liu."""
    show_version()

    print()
    print("usage:")
    print("\t liu quickstart")
    print("\t OR")
    print("\t liu create portfolio <amount> [--credit=<credit>]")
    print("\n")
    print("options:")
    print("\t--credit\tAccount credit line")
    print()


def _database_location() -> str:
    url = database_url(config.dsn)
    if url.get_backend_name() == "sqlite":
        return url.database or "an in-memory SQLite database"
    return url.render_as_string(hide_password=True)


def setup_db() -> None:
    """Create or upgrade the database schema.

    Exit the process if the database cannot be reached.
    """
    print()
    print("+---------------------+")
    print("| setting up database |")
    print("+---------------------+")
    print()
    try:
        get_event_loop().run_until_complete(upgrade_schema())
    except Exception as e:
        print(f"Something went wrong:{e}")
        print(
            "Check the DSN environment variable, or unset it to use the default SQLite database."
        )
        exit(0)

    print(f"database ready at {_database_location()}")


def setup_samples(samples_location: str) -> None:
    """Download the quickstart samples.

    Exit the process if any download fails.

    Parameters
    ----------
    samples_location: str
        The directory for the samples, created if missing.
    """
    try:
        print()
        print("+--------------------+")
        print("| setting up samples |")
        print("+--------------------+")

        p = pathlib.Path(samples_location)
        if not p.exists():
            p.mkdir()
        if samples_location[-1] != "/":
            samples_location += "/"

        base_url = "https://raw.github.com/amor71/LiuAlgoTrader/master/examples/quickstart/"
        files = [
            "tradeplan.toml",
            "vwap_short.py",
            "momentum_long_simplified.py",
        ]

        for file in files:
            print(f"Downloading {base_url}{file} to {samples_location}...")
            r = requests.get(f"{base_url}{file}")
            with open(f"{samples_location}{file}", "w") as f:
                f.write(r.text)
                f.write("")

    except Exception as e:
        print(f"Something went wrong:{e}")
        print(
            "Pls open a new issue w/ details 'https://github.com/amor71/LiuAlgoTrader/issues/new'"
        )
        exit(0)


def quickstart():
    """Guide the user interactively through the initial framework setup.

    Create the database and download the samples as the user selects. Exit the
    process if the Alpaca API key and secret are not configured.
    """
    print(f"Welcome to Liu Algo Trading Framework v{config.build_label}!")
    print()
    print("This wizard will guide you through the setup process.")
    print()
    print("+----------------------------------------+")
    print("| Step #1 - Alpaca & Polygon credentials |")
    print("+----------------------------------------+")
    print()
    print(
        "To use Liu Algo Trading Framework you need an account with Alpaca Markets,"
    )
    print("do you already have an account [Y]/n:")
    i = input()
    have_funded = len(i) == 0 or (i == "y" or i == "Y" or i.lower() == "yes")

    if not have_funded:
        print("For additional details `https://alpaca.markets/docs/about-us/`")
        return

    to_exit = False
    if not (os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY")):
        print(
            "Liu Algo Trading Framework uses Alpaca for both LIVE and PAPER trading."
        )
        print()
        print("The Framework expects three environment variables to be set:")
        print(
            "`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`: reflecting the funded"
        )
        print("account's API key and secret respectively.")
        print(
            "And `APCA_API_BASE_URL` reflecting the base URL for your account."
        )
        print(
            "Please set the three environment variables and re-run the wizard."
        )
        to_exit = True

    if to_exit:
        sys.exit(0)

    print()
    print("+--------------------+")
    print("| Step #2 - Database |")
    print("+--------------------+")
    print()
    print(
        "Liu Algo Trading Framework keeps track of your trading in a database:"
    )
    print(_database_location())
    if not config.dsn:
        print()
        print(
            "This is a local SQLite file, so there is nothing to install. To use a"
        )
        print("PostgreSQL database instead, set the DSN environment variable,")
        print("e.g. `export DSN=postgresql://user:password@host/db`.")

    print()
    print("+--------------------+")
    print("| Step #3 - Examples |")
    print("+--------------------+")
    print()
    print("Would you like to download & view samples? [Y]/n:")
    i = input()
    samples = not len(i) or i.lower() in ("y", "yes")
    sample_location = None
    if samples:
        pwd = pathlib.Path().absolute()
        print(f"Select location for sample files [{pwd}/liu_samples]:")
        sample_location = input()
        sample_location = (
            f"{pwd}/liu_samples"
            if not len(sample_location)
            else sample_location
        )

    print()
    print("Ready to go?? Press [ENTER] to start the installation..")
    input()

    setup_db()
    if samples:
        setup_samples(sample_location)
    print("setup completed successfully.")
    print()
    print()
    print("+---------------+")
    print("| what's next?  |")
    print("+---------------+")
    print()
    print("Congratulations, Liu Algo Trader is ready to go!")
    print(
        "From here, you can either run the back-testing UI, or read the docs."
    )
    print(
        "The full documentation is available here: `https://liualgotrader.rtfd.io`."
    )
    print()

    if sample_location:
        print("To experience Liu Algo Trading for the first time:")
        print(
            f"1. change your working directory to the sample directory {sample_location} ('cd {sample_location}'),"
        )
        print(
            "2. back-test the sample strategies on a past day ('backtester from <YYYY-MM-DD>'),"
        )
        print(
            "3.`streamlit run https://raw.github.com/amor71/LiuAlgoTrader/master/analysis/backtester_ui.py`"
        )
        print(
            "4. select the 'analyzer' app, and paste the batch-id that the backtester printed."
        )

    print()
    print("Thank you for choosing Liu Algo Trading Framework. ")
    print()


def create_account(amount: float, credit: float):
    """Create an account and print its identifier.

    Parameters
    ----------
    amount: float
        The opening balance.
    credit: float
        The credit line; a positive value allows a negative balance.
    """
    loop = get_event_loop()
    loop.run_until_complete(create_db_connection())
    account_id = loop.run_until_complete(
        Account.create(amount, allow_negative=credit > 0, credit_line=credit)
    )
    print(f"Account ID {account_id} created")


def create_portfolio(amount: float, credit: float):
    """Create a portfolio and print its identifier.

    Parameters
    ----------
    amount: float
        The portfolio size.
    credit: float
        The credit line.
    """
    portfolio_id = str(uuid.uuid4())
    loop = get_event_loop()
    loop.run_until_complete(create_db_connection())
    loop.run_until_complete(
        Portfolio.save(
            portfolio_id=portfolio_id,
            portfolio_size=amount,
            credit=credit,
            parameters={},
        )
    )
    print(f"Portfolio ID {portfolio_id} created")


def main_cli() -> None:
    """Run the liu command-line interface and exit.

    Support the quickstart command, which runs the setup wizard, and the create
    portfolio command, which takes a positive amount and an optional positive
    credit line. Print the usage text for a missing or unknown command.
    """
    configure_logging()
    config.filename = os.path.basename(__file__)

    if len(sys.argv) < 2:
        show_usage()
        exit(0)

    if sys.argv[1] == "quickstart":
        try:
            quickstart()
        except KeyboardInterrupt:
            print("Oops... exiting gracefully")
    elif sys.argv[1] == "create":
        try:
            if sys.argv[2] == "portfolio":
                if float(sys.argv[3]) <= 0.0:
                    print(
                        "Oops.. account size must be positive. Always think positive w/ Liu"
                    )
                    exit(0)
                amount = float(sys.argv[3])

                credit = 0.0
                opts, args = getopt.getopt(
                    sys.argv[4:],
                    shortopts="",
                    longopts=[
                        "credit=",
                    ],
                )
                for opt, arg in opts:
                    if opt in ("--credit"):
                        credit = float(arg)
                        if credit <= 0.0:
                            print(
                                "Oops.. creditamount must be positive. Always think positive w/ Liu"
                            )
                            exit(0)

                create_portfolio(amount, credit)
        except Exception as e:
            print(f"[ERROR] {e}")
            show_usage()
    else:
        show_usage()

    exit(0)
