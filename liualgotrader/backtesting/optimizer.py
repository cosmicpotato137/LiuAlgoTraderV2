"""Run and record the back-tests of a hyper-parameter optimizer session.

Classes
-------
BacktestSettings
    The time scale, asset type and fees of the back-tests.

Functions
---------
save_optimizer_session
    Record a back-test batch in an optimizer session.
backtest_iteration
    Run one back-test and record it.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from liualgotrader import enhanced_backtest
from liualgotrader.common import config
from liualgotrader.common.concurrency import reset_event_loop
from liualgotrader.common.hyperparameter import Hyperparameters
from liualgotrader.common.log import configure_logging
from liualgotrader.common.types import AssetType, TimeScale
from liualgotrader.db.models.optimizer import OptimizerRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestSettings:
    """The time scale, asset type and fees of an optimizer's back-tests.

    Attributes
    ----------
    scale: TimeScale, default TimeScale.day
        The time scale of the simulation.
    asset_type: AssetType, default AssetType.US_EQUITIES
        The type of assets traded, which sets the market schedule.
    buy_fee_percentage: float, default 0.0
        The buy fee, as a percentage of the trade value.
    sell_fee_percentage: float, default 0.0
        The sell fee, as a percentage of the trade value.
    """

    scale: TimeScale = TimeScale.day
    asset_type: AssetType = AssetType.US_EQUITIES
    buy_fee_percentage: float = 0.0
    sell_fee_percentage: float = 0.0


async def save_optimizer_session(
    optimizer_session_id: str,
    batch_id: str,
    hypers: Hyperparameters,
    score: float,
):
    """Record a back-test batch as part of an optimizer session.

    Parameters
    ----------
    optimizer_session_id: str
        The optimizer session identifier.
    batch_id: str
        The back-test batch identifier.
    hypers: Hyperparameters
        The hyper-parameter values, saved in string form.
    score: float
        The score of the batch.
    """
    await OptimizerRun.save(optimizer_session_id, batch_id, str(hypers), score)


def backtest_iteration(
    optimizer_session_id: str,
    start_date: date,
    end_date: date,
    tradeplan: list[dict],
    hypers: Hyperparameters,
    settings: BacktestSettings = BacktestSettings(),
):
    """Run one back-test and record it in the session.

    Intended as the target of a separate process. Record the batch, scored by
    its net cash flow, only if the back-test succeeds. Log any exception
    instead of raising it, and log the new batch identifier.

    Parameters
    ----------
    optimizer_session_id: str
        The optimizer session identifier.
    start_date: date
        The first date of the back-test.
    end_date: date
        The last date of the back-test.
    tradeplan: list[dict]
        The strategy files of the trade plan.
    hypers: Hyperparameters
        The hyper-parameter values being tested.
    settings: BacktestSettings, default BacktestSettings()
        The time scale, asset type and fees of the back-test.
    """
    configure_logging()
    logger.info(
        "starting backtest with start_date=%s, end_date=%s w/ trade plan=%s",
        start_date,
        end_date,
        tradeplan,
    )
    uid = str(uuid.uuid4())

    try:
        loop = reset_event_loop()
        trades = loop.run_until_complete(
            enhanced_backtest.backtest_main(
                uid,
                start_date,
                end_date,
                settings.scale,
                tradeplan,
                settings.buy_fee_percentage,
                settings.sell_fee_percentage,
                settings.asset_type,
            )
        )
    except KeyboardInterrupt:
        logger.info("backtest() - Caught KeyboardInterrupt")
    except Exception as e:
        logger.exception(
            "backtest() - exception of type %s with args %s",
            type(e).__name__,
            e.args,
        )
    else:
        loop.run_until_complete(
            save_optimizer_session(
                optimizer_session_id,
                uid,
                hypers,
                enhanced_backtest.net_cash_flow(trades),
            )
        )
    finally:
        logger.info("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=")
        logger.info("new batch-id: %s", uid)
