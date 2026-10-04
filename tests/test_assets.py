import logging

import pytest

from liualgotrader.common import assets

logger = logging.getLogger(__name__)


@pytest.mark.devtest
def test_round_asset() -> bool:
    f = 0.999349343434
    logger.info("%s %s", f, assets.round_asset("BTCUSD", f))

    return True
