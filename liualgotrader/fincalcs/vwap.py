"""Volume-weighted average price (VWAP) calculations.

Functions
---------
add_daily_vwap
    Compute the VWAP of price bars from an anchor time.
anchored_vwap
    Return the VWAP series anchored at a start time.
"""

import logging
from typing import Optional

import pandas as pd
from pandas import DataFrame as df

from liualgotrader.common import config

logger = logging.getLogger(__name__)


def add_daily_vwap(
    minute_data: df,
    debug=False,
    back_time: Optional[pd.Timestamp] = None,
    in_place=True,
):
    """Compute the volume-weighted average price from an anchor time.

    Add average, pv, apv, av and vwap columns; the last three are missing
    before the anchor.

    Parameters
    ----------
    minute_data: df
        The price bars, with close, high, low and volume columns.
    debug, default False
        Log the input and any lookup error.
    back_time: Optional[pd.Timestamp], default None
        The anchor time, matched to the nearest row.
    in_place, default True
        Modify minute_data rather than a copy.

    Returns
    -------
    Return True if in_place is set, otherwise the vwap series from the anchor
    onward. Return False if the anchor cannot be located.
    """
    if debug:
        logger.info("before vwap %s", minute_data)

    try:
        back_time_index = minute_data["close"].index.get_indexer(
            [back_time], method="nearest"
        )[0]
    except Exception as e:
        if debug:
            logger.error(
                "IndexError exception %s in add_daily_vwap for %s",
                e,
                minute_data,
            )
        return False

    df = minute_data if in_place else minute_data.copy()

    df["average"] = df.apply(
        lambda x: (x.close + x.high + x.low) / 3.0, axis=1
    )
    df["pv"] = df.apply(lambda x: x.average * x.volume, axis=1)
    df["apv"] = df["pv"][back_time_index:].cumsum()
    df["av"] = df["volume"][back_time_index:].cumsum()
    df["vwap"] = df["apv"] / df["av"]

    return (
        True
        if in_place
        else df[
            df.close.index.get_indexer([back_time], method="nearest")[0] :
        ].vwap
    )


def anchored_vwap(
    ohlc_data: df, start_time: pd.Timestamp, debug=False
) -> pd.Series:
    """Return the volume-weighted average price anchored at a start time.

    Parameters
    ----------
    ohlc_data: df
        The price bars, which are left unmodified.
    start_time: pd.Timestamp
        The anchor time, matched to the nearest row.
    debug, default False
        Log the input and any lookup error.

    Returns
    -------
    Return the vwap series from the anchor onward, or False if the anchor
    cannot be located.
    """
    return add_daily_vwap(
        ohlc_data, debug=debug, back_time=start_time, in_place=False
    )
