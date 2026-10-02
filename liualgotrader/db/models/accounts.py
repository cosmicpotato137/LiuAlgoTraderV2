"""Persist and load accounts and their transactions.

Classes
-------
Account
    Account with a balance, stored in the accounts table.
AccountTransaction
    Change to the balance of an account, stored in account_transactions.
"""

import datetime
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy import DateTime, ForeignKey, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from liualgotrader.common.tlog import tlog
from liualgotrader.db.models.base import Base
from liualgotrader.db.session import fetch_as_dataframe, session_scope


class Account(Base):
    """Account with a balance, stored in the accounts table.

    The database adds the amount of every saved AccountTransaction to the
    balance of its account.

    Attributes
    ----------
    account_id: int
        The account identifier, or None until the account is saved.
    balance: float
        The current balance.
    allow_negative: bool
        Whether the balance may go below zero.
    credit_line: float
        The credit available below zero; must be positive if allow_negative.
    details: Optional[Dict[str, Any]]
        Extra account details, or None.
    create_tstamp: Optional[datetime.datetime]
        The creation time, set by the database when the account is saved.
    modify_tstamp: Optional[datetime.datetime]
        The time of the last transaction, or None.

    Methods
    -------
    create
        Create an account and return its identifier.
    check_if_enough_balance_to_withdraw
        Check that a withdrawal is covered.
    get_balance
        Return the balance of an account.
    add_transaction
        Record a transaction against an account.
    get_transactions
        Return the transactions of an account.
    clear_balance
        Overwrite the balance of an account.
    clear_account_transactions
        Delete the transactions of an account.
    """

    __tablename__ = "accounts"

    account_id: Mapped[int] = mapped_column(primary_key=True)
    balance: Mapped[float] = mapped_column(server_default="0.0")
    allow_negative: Mapped[bool] = mapped_column(server_default="false")
    credit_line: Mapped[float] = mapped_column(server_default="0.0")
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    create_tstamp: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    modify_tstamp: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    @classmethod
    async def create(
        cls,
        balance: float,
        allow_negative: bool = False,
        credit_line: float = 0.0,
        details: Dict = {},
    ) -> int:
        """Create an account and return its identifier.

        Parameters
        ----------
        balance: float
            The opening balance.
        allow_negative: bool, default False
            Whether the balance may go below zero.
        credit_line: float, default 0.0
            The credit available below zero.
        details: Dict, default {}
            Extra account details, stored as JSON.
        """
        account = cls(
            balance=balance,
            allow_negative=allow_negative,
            credit_line=credit_line,
            details=details,
        )
        async with session_scope() as session:
            session.add(account)

        return account.account_id

    @classmethod
    async def check_if_enough_balance_to_withdraw(
        cls, account_id: int, potential_withdraw: float
    ) -> bool:
        """Return whether an account can cover a withdrawal.

        Parameters
        ----------
        account_id: int
            The account identifier.
        potential_withdraw: float
            The amount to withdraw.

        Returns
        -------
        Return True if the balance exceeds the amount, or if the account allows
        a negative balance and the balance plus the credit line exceeds it.

        Raises
        ------
        Raise AssertionError if potential_withdraw is negative, or
        sqlalchemy.exc.NoResultFound if the account does not exist.
        """
        if potential_withdraw < 0:
            raise AssertionError(
                f"check_if_enough_balance(): potential transaction amount ({potential_withdraw}) can't be negative "
            )

        async with session_scope() as session:
            account = await session.get_one(cls, account_id)

        return account.balance > potential_withdraw or (
            account.allow_negative
            and account.balance + account.credit_line > potential_withdraw
        )

    @classmethod
    async def get_balance(cls, account_id: int) -> Optional[float]:
        """Return the balance of an account.

        Parameters
        ----------
        account_id: int
            The account identifier.

        Returns
        -------
        Return None if the account does not exist.
        """
        async with session_scope() as session:
            return await session.scalar(
                select(cls.balance).where(cls.account_id == account_id)
            )

    @classmethod
    async def add_transaction(
        cls,
        account_id: int,
        amount: float,
        tstamp: Optional[datetime.datetime] = None,
        details: Dict = {},
    ) -> None:
        """Record a transaction against an account and update its balance.

        Parameters
        ----------
        account_id: int
            The account identifier.
        amount: float
            The amount added to the balance, negative for a withdrawal.
        tstamp: Optional[datetime.datetime], default None
            The transaction time, or None for the current time.
        details: Dict, default {}
            Extra transaction details, stored as JSON.

        Raises
        ------
        Log and re-raise any database error.
        """
        transaction = AccountTransaction(
            account_id=account_id, amount=amount, details=details
        )
        if tstamp:
            transaction.tstamp = tstamp

        try:
            async with session_scope() as session:
                session.add(transaction)
        except Exception as e:
            tlog(
                f"[EXCEPTION] add_transaction({account_id}, {amount}, {tstamp} ) failed with {e} current balance={await cls.get_balance(account_id)}"
            )
            raise

    @classmethod
    async def get_transactions(cls, account_id: int) -> pd.DataFrame:
        """Return the transactions of an account as a DataFrame.

        The DataFrame holds the amounts, indexed and sorted by timestamp.

        Parameters
        ----------
        account_id: int
            The account identifier.

        Returns
        -------
        Return an empty DataFrame if the account has no transactions.
        """
        df = await fetch_as_dataframe(
            select(AccountTransaction.tstamp, AccountTransaction.amount).where(
                AccountTransaction.account_id == account_id
            )
        )
        return (
            df.set_index("tstamp", drop=True).sort_index()
            if not df.empty
            else df
        )

    @classmethod
    async def clear_balance(cls, account_id: int, new_balance: float) -> None:
        """Overwrite the balance of an account without recording a transaction.

        Parameters
        ----------
        account_id: int
            The account identifier.
        new_balance: float
            The balance to set.

        Raises
        ------
        Log and re-raise any database error.
        """
        try:
            async with session_scope() as session:
                await session.execute(
                    update(cls)
                    .where(cls.account_id == account_id)
                    .values(balance=new_balance)
                )
        except Exception as e:
            tlog(
                f"[EXCEPTION] clear_balance() failed with {e} current balance={await cls.get_balance(account_id)}"
            )
            raise

    @classmethod
    async def clear_account_transactions(cls, account_id: int) -> None:
        """Delete all transactions of an account without changing its balance.

        Parameters
        ----------
        account_id: int
            The account identifier.

        Raises
        ------
        Log and re-raise any database error.
        """
        try:
            async with session_scope() as session:
                await session.execute(
                    delete(AccountTransaction).where(
                        AccountTransaction.account_id == account_id
                    )
                )
        except Exception as e:
            tlog(
                f"[EXCEPTION] clear_account_transactions() failed with {e} current balance={await cls.get_balance(account_id)}"
            )
            raise


class AccountTransaction(Base):
    """Change to the balance of an account, stored in account_transactions.

    Attributes
    ----------
    transaction_id: int
        The transaction identifier, or None until the transaction is saved.
    account_id: int
        The identifier of the account.
    amount: float
        The amount added to the balance, negative for a withdrawal.
    details: Optional[Dict[str, Any]]
        Extra transaction details, or None.
    tstamp: Optional[datetime.datetime]
        The transaction time, which defaults to the time it is saved.
    create_tstamp: Optional[datetime.datetime]
        The creation time, set by the database when the transaction is saved.
    """

    __tablename__ = "account_transactions"

    transaction_id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"))
    amount: Mapped[float]
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    tstamp: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    create_tstamp: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
