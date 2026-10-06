import logging
from datetime import datetime

import hypothesis.strategies as st
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis.extra.pandas import indexes, series

from liualgotrader.common import clock
from liualgotrader.fincalcs.trends import SeriesTrendType, get_series_trend

logger = logging.getLogger(__name__)


@settings(max_examples=200)
@given(
    series(
        index=indexes(
            elements=st.datetimes(
                min_value=datetime(2000, 1, 1),
                max_value=datetime(2040, 1, 1),
                timezones=st.just(clock.NY),
                allow_imaginary=False,
            ).map(pd.Timestamp),
            dtype=None,
        ),
        elements=st.floats(
            allow_nan=False,
            allow_infinity=False,
        ),
        dtype=float,
    ),
)
@pytest.mark.devtest
def test_get_series_trend(serie: pd.Series):
    logger.info("%s", serie)
    r, t = get_series_trend(serie)
    logger.info("result %s %s", r, t)
