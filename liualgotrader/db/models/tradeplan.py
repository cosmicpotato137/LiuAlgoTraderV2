"""Load the trade plan entries that assign strategies to portfolios.

Classes
-------
TradePlan
    Strategy assigned to a portfolio, stored in the trade_plan table.
"""

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import ForeignKey, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.common import clock
from liualgotrader.db.models.base import (Base, CurrentTimestamp, JsonDict,
                                          RandomUuid)
from liualgotrader.db.session import session_scope


class TradePlan(Base):
    """Strategy assigned to a portfolio, stored in the trade_plan table.

    An entry is active from its start date until it expires.

    Attributes
    ----------
    trade_plan_id: uuid.UUID
        The entry identifier, assigned by the database.
    portfolio_id: str
        The identifier of the portfolio the strategy trades.
    start_date: date
        The date the entry becomes active.
    strategy_name: str
        The name of the strategy.
    parameters: Optional[Dict[str, Any]]
        The strategy parameters, or None.
    create_tstamp: Optional[pd.Timestamp]
        The creation time, set by the database when the entry is saved.
    modify_tstamp: Optional[pd.Timestamp]
        The time of the last update through the ORM, or None.
    expire_tstamp: Optional[pd.Timestamp]
        The time the entry expired, or None.

    Methods
    -------
    load
        Load the active trade plan entries.
    get_new_entries
        Load the active entries created after a given time.
    """

    __tablename__ = "trade_plan"

    trade_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        primary_key=True,
        default=uuid.uuid4,
        server_default=RandomUuid(),
    )
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio.portfolio_id")
    )
    start_date: Mapped[date]
    strategy_name: Mapped[str]
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonDict)
    create_tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        server_default=CurrentTimestamp()
    )
    modify_tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        onupdate=CurrentTimestamp()
    )
    expire_tstamp: Mapped[Optional[pd.Timestamp]]

    def __str__(self):
        """Return the strategy name and parameters, separated by a colon."""
        return f"{self.strategy_name}:{self.parameters}"

    @classmethod
    async def load(cls) -> List["TradePlan"]:
        """Load the active trade plan entries."""
        return await cls._load_active()

    @classmethod
    async def get_new_entries(cls, since: pd.Timestamp) -> List["TradePlan"]:
        """Load the active trade plan entries created after a given time.

        Parameters
        ----------
        since: pd.Timestamp
            The time after which entries are included.
        """
        return await cls._load_active(cls.create_tstamp > since)

    @classmethod
    async def _load_active(cls, *criteria) -> List["TradePlan"]:
        async with session_scope() as session:
            entries = await session.scalars(
                select(cls).where(
                    cls.expire_tstamp.is_(None),
                    cls.start_date <= clock.today(),
                    *criteria,
                )
            )
            return list(entries)
