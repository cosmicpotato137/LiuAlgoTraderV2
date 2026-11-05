"""Exceptions raised by the framework.

Exceptions
----------
LiuException
    Base class for framework exceptions.
MarketClosedToday
    Exception for a market that is closed for the day.
OwnershipCollision
    A strategy requested an order for a symbol that another strategy owns.
"""

class LiuException(Exception):
    """Base class for framework exceptions."""


class MarketClosedToday(LiuException):
    """Exception for a market that is closed for the day."""


class OwnershipCollision(LiuException):
    """A strategy requested an order for a symbol that another strategy owns.

    Attributes
    ----------
    strategy: str
        The name of the strategy that requested the order.
    symbol: str
        The symbol.
    owner: str
        The name of the strategy that owns the symbol.
    """

    def __init__(self, strategy: str, symbol: str, owner: str):
        """Initialize the error.

        Parameters
        ----------
        strategy: str
            The name of the strategy that requested the order.
        symbol: str
            The symbol.
        owner: str
            The name of the strategy that owns the symbol.
        """
        super().__init__(f"{strategy} requested {symbol}, which {owner} owns")
        self.strategy = strategy
        self.symbol = symbol
        self.owner = owner
