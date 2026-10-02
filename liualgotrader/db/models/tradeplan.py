"""Load the trade plan entries that assign strategies to portfolios.

Classes
-------
TradePlan
    Strategy assigned to a portfolio, stored in the trade_plan table.
TradePlanExecutionAudit
    Execution of a trade plan entry, stored in trade_plan_execution_audit.
"""

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import Base
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
    create_tstamp: Optional[datetime]
        The creation time, set by the database when the entry is saved.
    modify_tstamp: Optional[datetime]
        The time of the last update, set by the database.
    expire_tstamp: Optional[datetime]
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
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio.portfolio_id")
    )
    start_date: Mapped[date]
    strategy_name: Mapped[str]
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    create_tstamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    modify_tstamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    expire_tstamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    def __str__(self):
        """Return the strategy name and parameters, separated by a colon."""
        return f"{self.strategy_name}:{self.parameters}"

    @classmethod
    async def load(cls) -> List["TradePlan"]:
        """Load the active trade plan entries."""
        return await cls._load_active()

    @classmethod
    async def get_new_entries(cls, since: datetime) -> List["TradePlan"]:
        """Load the active trade plan entries created after a given time.

        Parameters
        ----------
        since: datetime
            The time after which entries are included; a naive time is in
            the time zone of the database session.
        """
        # Bind a naive time without a time zone, so that the database reads
        # it in its session time zone rather than the client's local one.
        return await cls._load_active(
            cls.create_tstamp
            > literal(since, DateTime(timezone=since.tzinfo is not None))
        )

    @classmethod
    async def _load_active(cls, *criteria) -> List["TradePlan"]:
        async with session_scope() as session:
            entries = await session.scalars(
                select(cls).where(
                    cls.expire_tstamp.is_(None),
                    cls.start_date <= func.now(),
                    *criteria,
                )
            )
            return list(entries)


class TradePlanExecutionAudit(Base):
    """Execution of a trade plan entry, stored in trade_plan_execution_audit.

    Attributes
    ----------
    execution_id: int
        The record identifier, or None until the record is saved.
    trade_plan_id: Optional[uuid.UUID]
        The identifier of the executed trade plan entry, or None.
    details: Optional[Dict[str, Any]]
        Details of the execution, or None.
    started_on: Optional[datetime]
        The start time, which defaults to the time the record is saved.
    ended_on: Optional[datetime]
        The end time, which defaults to the time the record is saved.
    """

    __tablename__ = "trade_plan_execution_audit"

    execution_id: Mapped[int] = mapped_column(primary_key=True)
    trade_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_plan.trade_plan_id")
    )
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    started_on: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    ended_on: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
