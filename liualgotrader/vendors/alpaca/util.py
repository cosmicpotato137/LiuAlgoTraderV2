"""Helpers shared by the Alpaca vendor modules.

Functions
---------
is_crypto_symbol
    Return whether a symbol is a supported crypto pair.
crypto_pair
    Return a crypto pair in the Alpaca form.
alpaca_time
    Return a time received from Alpaca as a timestamp in New York time.
"""

import pandas as pd

from liualgotrader.common import clock


def is_crypto_symbol(symbol: str) -> bool:
    """Return whether a symbol is a supported crypto pair.

    Only the Bitcoin and Ethereum pairs quoted in US dollars are supported.

    Parameters
    ----------
    symbol: str
        The symbol to check, with or without a slash, in any case.
    """
    return symbol.lower() in {"eth/usd", "btc/usd", "ethusd", "btcusd"}


def crypto_pair(symbol: str) -> str:
    """Return a crypto pair in the upper-case, slash-separated Alpaca form.

    Parameters
    ----------
    symbol: str
        The crypto pair, with or without a slash, in any case.
    """
    if "/" not in symbol:
        symbol = f"{symbol[:3]}/{symbol[3:]}"
    return symbol.upper()


def alpaca_time(value) -> pd.Timestamp:
    """Return a time received from Alpaca as a timestamp in New York time.

    Parameters
    ----------
    value
        The time, as a datetime or an ISO 8601 string, in UTC if it has no
        time zone.
    """
    return pd.to_datetime(value, utc=True).tz_convert(clock.NY)
