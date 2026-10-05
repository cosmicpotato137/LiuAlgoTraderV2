import logging
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
#
# common.trading_data includes global variables, cross strategies that may be
# helpful
#
from liualgotrader.common.trading_data import (buy_indicators,
                                               last_used_strategy, open_orders,
                                               sell_indicators, stop_prices,
                                               target_prices)
from liualgotrader.strategy.base import Strategy, StrategyType

logger = logging.getLogger(__name__)

#
# TALIB is *NOT* available as part of LiuAlgoTrader distribution,
# though it's highly recommended.
# Dcumentation can be found here https://www.ta-lib.org/
#
# import talib
# from talib import BBANDS, MACD, RSI


class MyStrategy(Strategy):
    def __init__(
        self,
        batch_id: str,
        schedule: List[Dict],
        data_loader: DataLoader = None,
        fractional: bool = False,
        ref_run_id: int = None,
        my_arg1: int = 0,
        my_arg2: bool = False,
    ):
        super().__init__(
            name=type(self).__name__,
            type=StrategyType.SWING,
            batch_id=batch_id,
            ref_run_id=ref_run_id,
            schedule=[],
            data_loader=data_loader,
        )
        self.my_arg1 = my_arg1
        self.my_arg2 = my_arg2

    async def buy_callback(
        self,
        symbol: str,
        price: float,
        qty: float,
        now: datetime = None,
        trade_fee: float = 0.0,
    ) -> None:
        ...

    async def sell_callback(
        self,
        symbol: str,
        price: float,
        qty: float,
        now: datetime = None,
        trade_fee: float = 0.0,
    ) -> None:
        ...

    async def create(self) -> bool:
        """
        This function is called by the framework during the instantiation
        of the strategy. Keep in mind that running on multi-process environment
        it means that this function will be called at least once per spawned process.
        :return:
        """
        await super().create()
        logger.info("strategy %s created", self.name)
        return True

    async def should_run_all(self):
        return False

    async def run(
        self,
        symbol: str,
        shortable: bool,
        position: float,
        now: datetime,
        minute_history: pd.DataFrame,
        portfolio_value: float = None,
        debug: bool = False,
        backtesting: bool = False,
    ) -> Tuple[bool, Dict]:
        current_second_data = minute_history.iloc[-1]
        logger.info("%s position is %s", symbol, position)
        logger.info("%s data: %s", symbol, current_second_data)

        if await super().is_buy_time(now) and not position:
            #
            # Check for buy signals??
            #

            #
            # Global, cross strategies passed via the framework
            #
            target_prices[symbol] = current_second_data.close * 1.02
            stop_prices[symbol] = current_second_data.close * 0.99

            #
            # indicators *should* be filled
            #
            buy_indicators[symbol] = {"my_indicator": "random"}

            logger.info(
                "[%s] Submitting buy 10 shares of %s at %s",
                self.name,
                symbol,
                current_second_data.close,
            )
            return (
                True,
                {
                    "side": "buy",
                    "qty": str(10),
                    "type": "limit",
                    "limit_price": current_second_data.close,
                },
            )
        elif (
            await super().is_sell_time(now)
            and position > 0
            and last_used_strategy[symbol].name == self.name  # important!
            and (
                current_second_data.close >= target_prices[symbol]
                or current_second_data.close <= stop_prices[symbol]
            )
        ):
            # check if we already have open order
            if open_orders.get(symbol) is not None:
                logger.info(
                    "%s: open order for %s exists, skipping", self.name, symbol
                )
                return False, {}

            # Check for liquidation signals
            sell_indicators[symbol] = {
                "my_indicator": "reached target"
                if current_second_data.close >= target_prices[symbol]
                else "reached stop"
            }

            logger.info(
                "[%s] Submitting sell for %s shares of %s at market w/ %s",
                self.name,
                position,
                symbol,
                sell_indicators,
            )
            return (
                True,
                {
                    "side": "sell",
                    "qty": str(position),
                    "type": "market",
                },
            )

        return False, {}
