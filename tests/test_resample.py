import logging
from datetime import datetime

import hypothesis.strategies as st
import pandas as pd
from hypothesis import given, settings
from hypothesis.extra.pandas import columns, data_frames, indexes

from liualgotrader.common import clock
from liualgotrader.fincalcs.resample import ResampleRangeType, resample

logger = logging.getLogger(__name__)


@settings(deadline=None, max_examples=100)
@given(
    data_frames(
        index=indexes(
            elements=st.datetimes(
                min_value=datetime(2000, 1, 1),
                max_value=datetime(2040, 1, 1),
                timezones=st.just(clock.NY),
                allow_imaginary=False,
            ).map(pd.Timestamp),
            dtype=None,
        ),
        columns=columns(
            ["open", "close", "high", "low", "volume"], dtype=float
        ),
        rows=st.tuples(
            st.floats(allow_nan=True),
            st.floats(allow_nan=True),
            st.floats(allow_nan=True),
            st.floats(allow_nan=True),
            st.floats(allow_nan=True),
        ),
    ),
    st.sampled_from(ResampleRangeType),
)
def test_resample(ohlc: pd.DataFrame, resample_range: ResampleRangeType):
    logger.info("%s", ohlc.index)
    r = resample(ohlc, resample_range)
    if ohlc.empty:
        assert r.empty  # nosec
    else:
        assert not r.empty  # nosec

    logger.info("result %s", r)
