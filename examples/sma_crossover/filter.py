"""A custom filter that selects a fixed list of symbols.

Classes
-------
MyFilter
    Filter that selects the symbols listed in its settings.
"""

from typing import Optional

import pandas as pd

from liualgotrader.strategy.new_base import Filter


class MyFilter(Filter):
    """Filter that selects the symbols listed in its settings.

    Attributes
    ----------
    symbols: list[str]
        The symbols to select.
    """

    def __init__(self, symbols: Optional[list[str]] = None, **kwargs):
        """Initialize the filter.

        Parameters
        ----------
        symbols: Optional[list[str]], default None
            The symbols to select, or None for AAPL.
        """
        super().__init__(**kwargs)
        self.symbols = symbols or ["AAPL"]

    async def run(self, now: pd.Timestamp) -> list[str]:
        """Return the configured symbols, whatever the time.

        Parameters
        ----------
        now: pd.Timestamp
            The time to select as of, which is in the past when backtesting.
        """
        return self.symbols
