"""Persistence of the trade operations made by strategy runs.

Classes
-------
NewTrade
    Trade operation made by a strategy run, stored in the new_trades table.
"""

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import Enum, ForeignKey, Numeric, select, update
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.base import Base, CurrentTimestamp, JsonDict
from liualgotrader.db.session import session_scope

logger = logging.getLogger(__name__)


class NewTrade(Base):
    """Trade operation made by a strategy run, stored in the new_trades table.

    Create an unsaved trade with keyword arguments, such as
    NewTrade(algo_run_id=..., symbol=..., operation=..., qty=..., price=...,
    indicators=...).

    Attributes
    ----------
    trade_id: int
        The trade identifier, or None until the trade is saved.
    algo_run_id: int
        The identifier of the run making the trade.
    symbol: str
        The traded symbol.
    operation: str
        The operation: buy, sell, sell_short or buy_short.
    qty: Decimal
        The quantity traded.
    price: Decimal
        The trade price.
    indicators: Dict[str, Any]
        The indicators at the time of the trade.
    client_time: Optional[pd.Timestamp]
        The client-side time of the trade, or None.
    tstamp: Optional[pd.Timestamp]
        The time the trade was recorded, set by the database when saved.
    stop_price: Optional[Decimal]
        The stop price, or None.
    target_price: Optional[Decimal]
        The target price, or None.
    expire_tstamp: Optional[pd.Timestamp]
        The time the trade expired, or None.
    trade_fee: Decimal
        The fee paid for the trade.

    Methods
    -------
    save
        Save the trade as a new record.
    expire_trade
        Mark a trade as expired.
    load_latest
        Return the latest trade of a symbol for a strategy.
    get_run_symbols
        Return the symbols with unexpired trades in a run.
    rename_algo_run_id
        Move the trades of a symbol to another run.
    get_latest_algo_run_id
        Return the run of the latest trade of a symbol.
    """

    __tablename__ = "new_trades"

    trade_id: Mapped[int] = mapped_column(primary_key=True)
    algo_run_id: Mapped[int] = mapped_column(
        ForeignKey("algo_run.algo_run_id"), index=True
    )
    symbol: Mapped[str] = mapped_column(index=True)
    operation: Mapped[str] = mapped_column(
        Enum(
            "buy",
            "sell",
            "sell_short",
            "buy_short",
            name="trade_operation",
            create_constraint=True,
        )
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    indicators: Mapped[Dict[str, Any]] = mapped_column(JsonDict)
    client_time: Mapped[Optional[pd.Timestamp]]
    tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        server_default=CurrentTimestamp(), index=True
    )
    stop_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    target_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    expire_tstamp: Mapped[Optional[pd.Timestamp]]
    trade_fee: Mapped[Decimal] = mapped_column(
        Numeric(9, 2), server_default="0.0"
    )

    async def save(
        self,
        client_time: pd.Timestamp,
        stop_price=None,
        target_price=None,
        trade_fee=0.0,
    ) -> None:
        """Save this trade as a new record and set trade_id.

        Replace the indicators with an empty dictionary if they contain values
        that JSON cannot represent, such as NaN.

        Parameters
        ----------
        client_time: pd.Timestamp
            The client-side time of the trade.
        stop_price, default None
            The stop price, or None.
        target_price, default None
            The target price, or None.
        trade_fee, default 0.0
            The fee paid for the trade.
        """
        try:
            json.dumps(self.indicators or {}, allow_nan=False)
            self.indicators = self.indicators or {}
        except ValueError:
            self.indicators = {}

        self.client_time = client_time
        self.stop_price = stop_price
        self.target_price = target_price
        self.trade_fee = trade_fee
        async with session_scope() as session:
            session.add(self)

    @classmethod
    async def expire_trade(cls, trade_id: int) -> None:
        """Mark a trade as expired as of the current time.

        Parameters
        ----------
        trade_id: int
            The trade identifier.
        """
        async with session_scope() as session:
            await session.execute(
                update(cls)
                .where(cls.trade_id == trade_id)
                .values(expire_tstamp=CurrentTimestamp())
            )

    @classmethod
    async def load_latest(
        cls, symbol: str, strategy_name: str
    ) -> Tuple[
        int, float, float, float, Dict[str, Any], Optional[pd.Timestamp]
    ]:
        """Return the latest trade of a symbol made by a strategy.

        Missing prices are returned as 0.0 and missing indicators as an empty
        dictionary.

        Parameters
        ----------
        symbol: str
            The traded symbol.
        strategy_name: str
            The name of the strategy.

        Returns
        -------
        Return a tuple of the run identifier, price, stop price, target price,
        indicators and trade time.

        Raises
        ------
        Raise ValueError if the strategy has no trade in the symbol.
        """
        async with session_scope() as session:
            trade = await session.scalar(
                select(cls)
                .join_from(
                    cls, AlgoRun, cls.algo_run_id == AlgoRun.algo_run_id
                )
                .where(
                    AlgoRun.strategy_name == strategy_name,
                    cls.symbol == symbol,
                )
                .order_by(cls.tstamp.desc(), cls.trade_id.desc())
                .limit(1)
            )

        if trade:
            return (
                int(trade.algo_run_id),
                float(trade.price),
                float(trade.stop_price or 0.0),
                float(trade.target_price or 0.0),
                trade.indicators or {},
                trade.tstamp,
            )
        logger.info("%s no data for strategy %s", symbol, strategy_name)
        raise ValueError

    @classmethod
    async def get_run_symbols(cls, algo_run_id: int) -> List[str]:
        """Return the symbols that have unexpired trades in a run.

        Parameters
        ----------
        algo_run_id: int
            The run identifier.
        """
        async with session_scope() as session:
            symbols = await session.scalars(
                select(cls.symbol)
                .where(
                    cls.algo_run_id == algo_run_id,
                    cls.expire_tstamp.is_(None),
                )
                .distinct()
            )
            return list(symbols)

    @classmethod
    async def rename_algo_run_id(
        cls, new_algo_run_id: int, old_algo_run_id: int, symbol: str
    ) -> None:
        """Move the trades of a symbol from one run to another.

        Parameters
        ----------
        new_algo_run_id: int
            The identifier of the run receiving the trades.
        old_algo_run_id: int
            The identifier of the run that made the trades.
        symbol: str
            The traded symbol.
        """
        async with session_scope() as session:
            await session.execute(
                update(cls)
                .where(
                    cls.algo_run_id == old_algo_run_id,
                    cls.symbol == symbol,
                )
                .values(algo_run_id=new_algo_run_id)
            )

    @classmethod
    async def get_latest_algo_run_id(cls, symbol: str) -> Optional[int]:
        """Return the run identifier of the latest trade of a symbol.

        Parameters
        ----------
        symbol: str
            The traded symbol.

        Returns
        -------
        Return None if the symbol has no trades.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(cls.algo_run_id)
                .where(cls.symbol == symbol)
                .order_by(cls.tstamp.desc(), cls.trade_id.desc())
                .limit(1)
            )
