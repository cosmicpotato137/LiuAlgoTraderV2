"""Persist and load the batches run by optimizer sessions.

Classes
-------
OptimizerRun
    Batch run by an optimizer session, stored in the optimizer_run table.
"""

from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.base import Base, CurrentTimestamp
from liualgotrader.db.models.portfolio import PortfolioBatchId
from liualgotrader.db.session import session_scope


class OptimizerRun(Base):
    """Batch run by an optimizer session, stored in the optimizer_run table.

    Attributes
    ----------
    optimizer_run_id: int
        The record identifier, or None until the record is saved.
    optimizer_session_id: str
        The optimizer session identifier.
    batch_id: str
        The batch identifier.
    tstamp: Optional[pd.Timestamp]
        The creation time, set by the database when the record is saved.
    parameters: str
        The parameters used for the batch.

    Methods
    -------
    save
        Record a batch run by an optimizer session.
    get_portfolio_ids_parameters
        Return the portfolios of a session.
    """

    __tablename__ = "optimizer_run"

    optimizer_run_id: Mapped[int] = mapped_column(primary_key=True)
    optimizer_session_id: Mapped[str] = mapped_column(index=True)
    batch_id: Mapped[str]
    tstamp: Mapped[Optional[pd.Timestamp]] = mapped_column(
        server_default=CurrentTimestamp()
    )
    parameters: Mapped[str] = mapped_column(server_default="")

    @classmethod
    async def save(
        cls, optimizer_session_id: str, batch_id: str, parameters: str
    ) -> None:
        """Record a batch run as part of an optimizer session.

        Parameters
        ----------
        optimizer_session_id: str
            The optimizer session identifier.
        batch_id: str
            The batch identifier.
        parameters: str
            The parameters used for the batch.
        """
        async with session_scope() as session:
            session.add(
                cls(
                    optimizer_session_id=optimizer_session_id,
                    batch_id=batch_id,
                    parameters=parameters,
                )
            )

    @classmethod
    async def get_portfolio_ids_parameters(
        cls,
        optimizer_session_id: str,
    ) -> List[Tuple[str, str]]:
        """Return the portfolios of an optimizer session and their parameters.

        Connect to the database first if it is not connected yet.

        Parameters
        ----------
        optimizer_session_id: str
            The optimizer session identifier.

        Returns
        -------
        Return a list of (portfolio_id, parameters) tuples, one for each batch
        of the session.
        """
        async with session_scope() as session:
            rows = await session.execute(
                select(PortfolioBatchId.portfolio_id, cls.parameters)
                .join_from(
                    cls,
                    PortfolioBatchId,
                    cls.batch_id == PortfolioBatchId.batch_id,
                )
                .where(cls.optimizer_session_id == optimizer_session_id)
            )
            return [(row[0], row[1]) for row in rows]
