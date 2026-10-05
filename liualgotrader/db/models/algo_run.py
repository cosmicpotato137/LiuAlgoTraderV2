"""Persist and load strategy runs and their batches.

Classes
-------
AlgoRun
    Single strategy run within a batch, stored in the algo_run table.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pandas import DataFrame
from sqlalchemy import ForeignKey, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.common import config
from liualgotrader.db.models.base import Base, CurrentTimestamp, JsonDict
from liualgotrader.db.session import session_scope


class AlgoRun(Base):
    """Single strategy run within a batch, stored in the algo_run table.

    Create an unsaved run with keyword arguments, such as
    AlgoRun(strategy_name=..., batch_id=...).

    Attributes
    ----------
    algo_run_id: int
        The run identifier, or None until the run is saved.
    strategy_name: str
        The name of the strategy.
    env: str
        The environment the run executes in.
    build_number: str
        The build label of the framework.
    parameters: Optional[Dict[str, Any]]
        The run parameters, or None.
    start_time: Optional[datetime]
        The start time, set by the database when the run is saved.
    end_time: Optional[datetime]
        The end time, or None while the run is active.
    end_reason: Optional[str]
        The reason the run ended, or None.
    batch_id: str
        The identifier of the batch the run belongs to.
    ref_algo_run_id: Optional[int]
        The identifier of a related run, or None.

    Methods
    -------
    save
        Save the run as a new record.
    update_end_time
        Mark the run as ended.
    get_batch_ids
        Return the identifiers of batches started after a date.
    get_batches
        Return a summary of the most recent batches.
    get_batch_list_by_date
        Return the runs started on a date, by batch.
    get_batch_details
        Return the runs of a batch.
    """

    __tablename__ = "algo_run"

    algo_run_id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str]
    env: Mapped[str]
    build_number: Mapped[str]
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonDict)
    start_time: Mapped[Optional[datetime]] = mapped_column(
        server_default=CurrentTimestamp(), index=True
    )
    end_time: Mapped[Optional[datetime]]
    end_reason: Mapped[Optional[str]]
    batch_id: Mapped[str] = mapped_column(server_default="", index=True)
    ref_algo_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("algo_run.algo_run_id")
    )

    async def save(
        self,
        env: str = "unknown",
        ref_algo_run_id: Optional[int] = None,
    ) -> None:
        """Save this run as a new record and set algo_run_id.

        The record also holds the configured build label and DSN.

        Parameters
        ----------
        env: str, default "unknown"
            The environment name, with "unknown" used if empty.
        ref_algo_run_id: Optional[int], default None
            The identifier of a related run, or None.
        """
        self.env = env or "unknown"
        self.build_number = config.build_label
        self.parameters = {"DSN": config.dsn}
        self.ref_algo_run_id = ref_algo_run_id or None
        async with session_scope() as session:
            session.add(self)

    async def update_end_time(self, end_reason: str) -> None:
        """Mark this run as ended at the current time.

        Parameters
        ----------
        end_reason: str
            The reason the run ended.
        """
        async with session_scope() as session:
            self.end_time = await session.scalar(
                update(AlgoRun)
                .where(AlgoRun.algo_run_id == self.algo_run_id)
                .values(end_time=CurrentTimestamp(), end_reason=end_reason)
                .returning(AlgoRun.end_time)
            )
        self.end_reason = end_reason

    @classmethod
    async def get_batch_ids(
        cls, start_date: date = date(2019, 1, 1)
    ) -> DataFrame:
        """Return the distinct identifiers of batches with runs after a date.

        Parameters
        ----------
        start_date: date, default date(2019, 1, 1)
            The date after which runs are included.

        Returns
        -------
        Return a DataFrame with a single batch_id column.
        """
        async with session_scope() as session:
            batch_ids = await session.scalars(
                select(cls.batch_id)
                .where(cls.start_time > start_date)
                .distinct()
            )
            return DataFrame(data=batch_ids.all(), columns=["batch_id"])

    @classmethod
    async def get_batches(
        cls,
        nax_batches: int = 30,
        start_date: date = date(2019, 1, 1),
    ) -> List:
        """Return a summary of the most recent batches.

        Each entry lists the build number, batch identifier, strategy name and
        start time, all as strings.

        Parameters
        ----------
        nax_batches: int, default 30
            The maximum number of entries to return.
        start_date: date, default date(2019, 1, 1)
            The date after which runs are included.

        Returns
        -------
        Return a list, newest first, with one entry for each batch, strategy,
        environment and build.
        """
        start = func.min(cls.start_time)
        async with session_scope() as session:
            rows = await session.execute(
                select(
                    cls.build_number,
                    cls.batch_id,
                    cls.strategy_name,
                    start.label("start"),
                )
                .where(cls.start_time > start_date)
                .group_by(
                    cls.batch_id,
                    cls.strategy_name,
                    cls.env,
                    cls.build_number,
                )
                .order_by(start.desc())
                .limit(nax_batches)
            )
            return [
                [
                    build,
                    batch_id,
                    strategy,
                    str(start and start.replace(second=0, microsecond=0)),
                ]
                for build, batch_id, strategy, start in rows
            ]

    @classmethod
    async def get_batch_list_by_date(
        cls, batch_date: date
    ) -> Dict[str, List[Any]]:
        """Return the runs started on a date, grouped by batch.

        Each run lists its identifier, strategy name, environment, build number
        and start time.

        Parameters
        ----------
        batch_date: date
            The date the runs started.

        Returns
        -------
        Return a dictionary that maps each batch identifier to a list of runs,
        newest first.
        """
        runs: Dict[str, List[Any]] = {}
        async with session_scope() as session:
            rows = await session.execute(
                select(
                    cls.batch_id,
                    cls.algo_run_id,
                    cls.strategy_name,
                    cls.env,
                    cls.build_number,
                    cls.start_time,
                )
                .where(
                    cls.start_time >= batch_date,
                    cls.start_time < batch_date + timedelta(days=1),
                )
                .order_by(cls.start_time.desc(), cls.algo_run_id.desc())
            )
            for row in rows:
                runs.setdefault(row[0], []).append(list(row[1:]))

        return runs

    @classmethod
    async def get_batch_details(
        cls, batch_id: str
    ) -> List[Tuple[int, datetime, datetime, Optional[Dict[str, Any]]]]:
        """Return the runs of a batch, newest first.

        Each run is a tuple of its identifier, start time, end time and
        parameters.

        Parameters
        ----------
        batch_id: str
            The batch identifier.

        Returns
        -------
        Return an empty list if the batch has no runs.
        """
        async with session_scope() as session:
            rows = await session.execute(
                select(
                    cls.algo_run_id,
                    cls.start_time,
                    cls.end_time,
                    cls.parameters,
                )
                .where(cls.batch_id == batch_id)
                .order_by(cls.start_time.desc(), cls.algo_run_id.desc())
            )
            return [tuple(row) for row in rows]  # type: ignore
