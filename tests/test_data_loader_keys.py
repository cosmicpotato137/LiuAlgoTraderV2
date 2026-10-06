from datetime import date, datetime

import pandas as pd
import pytest

from liualgotrader.common.data_loader import SymbolData  # type: ignore
from liualgotrader.common.types import TimeScale

INVALID_KEYS = [
    "2021-01-05 09:45:00",
    date(2021, 1, 5),
    datetime(2021, 1, 5, 9, 45),
    pd.Timestamp("2021-01-05 09:45"),
]


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_rejects_key(key) -> None:
    data = SymbolData(None, "AAPL", TimeScale.minute, 0)
    with pytest.raises(TypeError, match="time zone-aware pd.Timestamp"):
        data[key]
    with pytest.raises(TypeError, match="time zone-aware pd.Timestamp"):
        data.close[key]


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_rejects_slice_bound(key) -> None:
    data = SymbolData(None, "AAPL", TimeScale.minute, 0)
    with pytest.raises(TypeError, match="time zone-aware pd.Timestamp"):
        data[key:key]
