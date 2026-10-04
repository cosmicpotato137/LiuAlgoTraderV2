"""Persist and load the gain and trade analyses of strategy runs.

Classes
-------
GainLoss
    Gain of a symbol in a strategy run, stored in the gain_loss table.
TradeAnalysis
    Result of a trade in a strategy run, stored in trade_analysis.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pandas import DataFrame
from sqlalchemy import ForeignKey, Numeric, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.base import Base, CurrentTimestamp, Timestamp
from liualgotrader.db.session import fetch_as_dataframe, session_scope

logger = logging.getLogger(__name__)


class GainLoss(Base):
    """Gain of a symbol in a strategy run, stored in the gain_loss table.

    Attributes
    ----------
    gain_loss_id: int
        The record identifier, or None until the record is saved.
    symbol: str
        The traded symbol; unique per run.
    algo_run_id: int
        The identifier of the run.
    gain_percentage: Decimal
        The gain as a percentage.
    gain_value: Decimal
        The gain as a value.
    tstamp: Optional[datetime]
        The creation time, set by the database when the record is saved.

    Methods
    -------
    save
        Save gain records from a DataFrame.
    load
        Return the gain records of runs started since a date.
    """

    __tablename__ = "gain_loss"
    __table_args__ = (UniqueConstraint("symbol", "algo_run_id"),)

    gain_loss_id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str]
    algo_run_id: Mapped[int] = mapped_column(
        ForeignKey("algo_run.algo_run_id")
    )
    gain_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    gain_value: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    tstamp: Mapped[Optional[datetime]] = mapped_column(
        server_default=CurrentTimestamp()
    )

    @classmethod
    async def save(cls, df: DataFrame) -> None:
        """Save each row of a DataFrame as a gain record.

        Log and skip any row that fails to save.

        Parameters
        ----------
        df: DataFrame
            The records, with symbol, algo_run_id, gain_percentage and
            gain_value columns.
        """
        async with session_scope() as session:
            for _, row in df.iterrows():
                try:
                    async with session.begin_nested():
                        session.add(
                            cls(
                                symbol=row.symbol,
                                algo_run_id=row.algo_run_id,
                                gain_percentage=row.gain_percentage,
                                gain_value=row.gain_value,
                            )
                        )
                except Exception as e:
                    logger.error(
                        "inserting %s resulted in exception %s", row, e
                    )

    @classmethod
    async def load(cls, start_date: date) -> DataFrame:
        """Return the gain records of runs started on or after a date.

        Parameters
        ----------
        start_date: date
            The earliest run start date to include.

        Returns
        -------
        Return a DataFrame with the symbol, strategy name, environment, run
        start time, gain percentage and gain value, sorted by symbol, strategy
        and start time.
        """
        return await fetch_as_dataframe(
            select(
                cls.symbol,
                AlgoRun.strategy_name,
                AlgoRun.env,
                AlgoRun.start_time,
                cls.gain_percentage,
                cls.gain_value,
            )
            .join_from(cls, AlgoRun, cls.algo_run_id == AlgoRun.algo_run_id)
            .where(AlgoRun.start_time >= start_date)
            .order_by(cls.symbol, AlgoRun.strategy_name, AlgoRun.start_time)
        )


class TradeAnalysis(Base):
    """Result of a trade in a strategy run, stored in trade_analysis.

    Attributes
    ----------
    trade_analysis_id: int
        The record identifier, or None until the record is saved.
    symbol: str
        The traded symbol.
    algo_run_id: int
        The identifier of the run.
    start_time: datetime
        The time the trade opened; unique per symbol and run.
    end_time: datetime
        The time the trade closed.
    gain_percentage: Decimal
        The gain as a percentage.
    gain_value: Decimal
        The gain as a value.
    r_units: Optional[Decimal]
        The gain in R-units, or None.
    tstamp: Optional[datetime]
        The creation time, set by the database when the record is saved.

    Methods
    -------
    save
        Save trade analysis records from a DataFrame.
    load
        Return the trade analyses of runs started since a date.
    """

    __tablename__ = "trade_analysis"
    __table_args__ = (UniqueConstraint("symbol", "algo_run_id", "start_time"),)

    trade_analysis_id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str]
    algo_run_id: Mapped[int] = mapped_column(
        ForeignKey("algo_run.algo_run_id")
    )
    start_time: Mapped[datetime] = mapped_column(Timestamp(timezone=True))
    end_time: Mapped[datetime] = mapped_column(Timestamp(timezone=True))
    gain_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    gain_value: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    r_units: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2))
    tstamp: Mapped[Optional[datetime]] = mapped_column(
        Timestamp(timezone=True), server_default=CurrentTimestamp()
    )

    @classmethod
    async def save(cls, df: DataFrame) -> None:
        """Save each row of a DataFrame as a trade analysis record.

        Log and skip any row that fails to save.

        Parameters
        ----------
        df: DataFrame
            The records, with symbol, algo_run_id, gain_percentage, gain_value,
            r_units, start_time and end_time columns.
        """
        async with session_scope() as session:
            for _, row in df.iterrows():
                try:
                    async with session.begin_nested():
                        session.add(
                            cls(
                                symbol=row.symbol,
                                algo_run_id=row.algo_run_id,
                                gain_percentage=row.gain_percentage,
                                gain_value=row.gain_value,
                                r_units=row.r_units,
                                start_time=row.start_time.to_pydatetime(),
                                end_time=row.end_time.to_pydatetime(),
                            )
                        )
                except Exception as e:
                    logger.error(
                        "inserting %s resulted in exception %s", row, e
                    )

    @classmethod
    async def load(cls, start_date: date) -> DataFrame:
        """Return the trade analyses of runs started on or after a date.

        Parameters
        ----------
        start_date: date
            The earliest run start date to include.

        Returns
        -------
        Return a DataFrame with the symbol, strategy name, environment,
        R-units, gain percentage, gain value and trade start and end times,
        sorted by symbol, strategy and run start time.
        """
        return await fetch_as_dataframe(
            select(
                cls.symbol,
                AlgoRun.strategy_name,
                AlgoRun.env,
                cls.r_units,
                cls.gain_percentage,
                cls.gain_value,
                cls.start_time,
                cls.end_time,
            )
            .join_from(cls, AlgoRun, cls.algo_run_id == AlgoRun.algo_run_id)
            .where(AlgoRun.start_time >= start_date)
            .order_by(cls.symbol, AlgoRun.strategy_name, AlgoRun.start_time)
        )
