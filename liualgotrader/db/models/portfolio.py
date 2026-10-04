"""Persist and load trading portfolios.

Classes
-------
Portfolio
    Trading portfolio backed by a dedicated account, stored in portfolio.
PortfolioBatchId
    Batch run for a portfolio, stored in the portfolio_batch_ids table.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pandas import DataFrame
from sqlalchemy import Enum, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.common.types import AssetType
from liualgotrader.db.models.accounts import Account, AccountTransaction
from liualgotrader.db.models.base import (Base, CurrentTimestamp, JsonDict,
                                          Timestamp)
from liualgotrader.db.session import session_scope


class Portfolio(Base):
    """Trading portfolio backed by a dedicated account, stored in portfolio.

    Attributes
    ----------
    portfolio_id: str
        The portfolio identifier.
    portfolio_size: int
        The portfolio size, which is also the opening account balance.
    parameters: Optional[Dict[str, Any]]
        The portfolio parameters, or None.
    expire_tstamp: Optional[datetime]
        The time the portfolio expired, or None.
    tstamp: Optional[datetime]
        The creation time, set by the database when the portfolio is saved.
    account_id: Optional[int]
        The identifier of the associated account, or None.
    asset_type: AssetType
        The type of assets the portfolio trades.
    external_account_id: Optional[str]
        The account identifier at the broker, or None.
    broker: Optional[str]
        The broker name, or None.

    Methods
    -------
    load_by_batch_id
        Load the portfolio associated with a batch.
    load_by_portfolio_id
        Load a portfolio by its identifier.
    save
        Create a portfolio and its account.
    associate_batch_id_to_profile
        Associate a batch with a portfolio.
    is_associated
        Return whether a portfolio has an associated batch.
    exists
        Return whether a portfolio exists.
    get_portfolio_account_balance
        Return the balance of a portfolio.
    get_external_account_id
        Return the external account and broker.
    list_portfolios
        Return the portfolios that have not expired.
    """

    __tablename__ = "portfolio"

    portfolio_id: Mapped[str] = mapped_column(primary_key=True)
    portfolio_size: Mapped[int]
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonDict)
    expire_tstamp: Mapped[Optional[datetime]] = mapped_column(
        Timestamp(timezone=True)
    )
    tstamp: Mapped[Optional[datetime]] = mapped_column(
        Timestamp(timezone=True), server_default=CurrentTimestamp()
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.account_id"), index=True
    )
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type", create_constraint=True),
        server_default=AssetType.US_EQUITIES.name,
    )
    external_account_id: Mapped[Optional[str]]
    broker: Mapped[Optional[str]]

    def __str__(self):
        """Return a readable description of the portfolio."""
        return f"id={self.portfolio_id} account-id={self.account_id} size={self.portfolio_size} asset_type={self.asset_type}, params={self.parameters}"

    @classmethod
    async def load_by_batch_id(cls, batch_id: str):
        """Load the portfolio associated with a batch.

        Connect to the database first if it is not connected yet.

        Parameters
        ----------
        batch_id: str
            The batch identifier.

        Returns
        -------
        Return a Portfolio, or None if the batch has no portfolio.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(cls)
                .join_from(
                    cls,
                    PortfolioBatchId,
                    cls.portfolio_id == PortfolioBatchId.portfolio_id,
                )
                .where(PortfolioBatchId.batch_id == batch_id)
                .limit(1)
            )

    @classmethod
    async def load_by_portfolio_id(cls, portfolio_id: str):
        """Load a portfolio by its identifier.

        Connect to the database first if it is not connected yet.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.

        Returns
        -------
        Return a Portfolio, or None if it does not exist.
        """
        async with session_scope() as session:
            return await session.get(cls, portfolio_id)

    @classmethod
    async def save(
        cls,
        portfolio_id: str,
        portfolio_size: float,
        credit: float,
        parameters: Dict,
        asset_type: AssetType = AssetType.US_EQUITIES,
        external_account_id: Optional[str] = None,
        broker: Optional[str] = None,
    ) -> None:
        """Create a portfolio together with a dedicated account.

        Create both or neither. Connect to the database first if it is not
        connected yet.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.
        portfolio_size: float
            The portfolio size and opening account balance.
        credit: float
            The credit line, where a positive value allows a negative balance.
        parameters: Dict
            The portfolio parameters, also stored as account details.
        asset_type: AssetType, default AssetType.US_EQUITIES
            The type of assets traded.
        external_account_id: Optional[str], default None
            The account identifier at the broker, or None.
        broker: Optional[str], default None
            The broker name, or None.
        """
        async with session_scope() as session:
            account = Account(
                balance=portfolio_size,
                allow_negative=credit > 0.0,
                credit_line=credit,
                details=parameters,
            )
            session.add(account)
            await session.flush()
            session.add(
                cls(
                    portfolio_id=portfolio_id,
                    portfolio_size=portfolio_size,
                    account_id=account.account_id,
                    asset_type=asset_type,
                    parameters=parameters,
                    external_account_id=external_account_id,
                    broker=broker,
                )
            )

    @classmethod
    async def associate_batch_id_to_profile(
        cls, portfolio_id: str, batch_id: str
    ) -> None:
        """Associate a batch with a portfolio.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.
        batch_id: str
            The batch identifier.
        """
        async with session_scope() as session:
            session.add(
                PortfolioBatchId(portfolio_id=portfolio_id, batch_id=batch_id)
            )

    @classmethod
    async def is_associated(
        cls, portfolio_id: str, batch_id: Optional[str] = None
    ) -> bool:
        """Return whether a portfolio is associated with a batch.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.
        batch_id: Optional[str], default None
            The batch to check, or None for any batch.
        """
        associations = select(PortfolioBatchId).where(
            PortfolioBatchId.portfolio_id == portfolio_id
        )
        if batch_id:
            associations = associations.where(
                PortfolioBatchId.batch_id == batch_id
            )

        async with session_scope() as session:
            return bool(await session.scalar(select(associations.exists())))

    @classmethod
    async def exists(cls, portfolio_id: str) -> bool:
        """Return whether a portfolio exists.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.
        """
        async with session_scope() as session:
            return bool(
                await session.scalar(
                    select(
                        select(cls)
                        .where(cls.portfolio_id == portfolio_id)
                        .exists()
                    )
                )
            )

    @classmethod
    async def get_portfolio_account_balance(
        cls, portfolio_id: str
    ) -> Optional[float]:
        """Return the balance of the account of a portfolio.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.

        Returns
        -------
        Return None if the portfolio does not exist.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(Account.balance)
                .join_from(Account, cls, Account.account_id == cls.account_id)
                .where(cls.portfolio_id == portfolio_id)
            )

    @classmethod
    async def get_external_account_id(
        cls, portfolio_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return the external account identifier and broker of a portfolio.

        Parameters
        ----------
        portfolio_id: str
            The portfolio identifier.

        Returns
        -------
        Return the two values as a tuple; either may be None.

        Raises
        ------
        Raise sqlalchemy.exc.NoResultFound if the portfolio does not exist.
        """
        async with session_scope() as session:
            portfolio = await session.get_one(cls, portfolio_id)

        return (portfolio.external_account_id, portfolio.broker)

    @classmethod
    async def list_portfolios(cls) -> DataFrame:
        """Return the portfolios that have not expired, newest first.

        A portfolio appears once for each of its account transactions, or once
        if it has none. Connect to the database first if it is not connected
        yet.

        Returns
        -------
        Return a DataFrame with the columns portfolio_id, last_transaction,
        portfolio_size, parameters, asset_type and tstamp.
        """
        async with session_scope() as session:
            rows = await session.execute(
                select(
                    cls.portfolio_id,
                    AccountTransaction.tstamp,
                    cls.portfolio_size,
                    cls.parameters,
                    cls.asset_type,
                    cls.tstamp,
                )
                .outerjoin_from(
                    cls,
                    AccountTransaction,
                    cls.account_id == AccountTransaction.account_id,
                )
                .where(cls.expire_tstamp.is_(None))
                .order_by(cls.tstamp.desc())
            )
            return DataFrame(
                data=rows.all(),
                columns=[
                    "portfolio_id",
                    "last_transaction",
                    "portfolio_size",
                    "parameters",
                    "asset_type",
                    "tstamp",
                ],
            )


class PortfolioBatchId(Base):
    """Batch run for a portfolio, stored in the portfolio_batch_ids table.

    Attributes
    ----------
    assoc_id: int
        The record identifier, or None until the record is saved.
    portfolio_id: str
        The portfolio identifier.
    batch_id: str
        The batch identifier.
    """

    __tablename__ = "portfolio_batch_ids"

    assoc_id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio.portfolio_id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(index=True)
