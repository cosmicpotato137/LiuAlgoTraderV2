"""Create the market calendar of an asset type.

Functions
---------
market_calendar_factory
    Return a new market calendar for an asset type.
"""

from liualgotrader.common import config
from liualgotrader.common.types import AssetType, DataConnectorType
from liualgotrader.market_calendar.base import (CryptoCalendar,
                                                MarketCalendarAPI)
from liualgotrader.vendors.alpaca.market_calendar import AlpacaCalendar


def market_calendar_factory(
    asset_type: AssetType, connector: DataConnectorType = None
) -> MarketCalendarAPI:
    """Return a new market calendar for an asset type.

    Crypto trades every day with any vendor. US equities follow the calendar
    of the connector, created with the connector's settings from config.

    Parameters
    ----------
    asset_type: AssetType
        The type of asset traded.
    connector: DataConnectorType, default None
        The vendor of the US equities calendar, or None for the configured
        calendar connector.

    Raises
    ------
    Raise AssertionError if the asset type is not supported, and Exception if
    the connector is not supported.
    """
    if asset_type == AssetType.CRYPTO:
        return CryptoCalendar()
    if asset_type != AssetType.US_EQUITIES:
        raise AssertionError(f"Asset type {asset_type} not supported yet")

    _connector = connector or config.calendar_connector
    if _connector == DataConnectorType.alpaca:
        return AlpacaCalendar(config.alpaca)
    raise Exception(f"unsupported market calendar provider {_connector}")
