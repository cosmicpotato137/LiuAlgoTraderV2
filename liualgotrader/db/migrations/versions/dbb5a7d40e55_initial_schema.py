"""Initial schema.

Create the tables of a new database. Make a database created before
migrations the same as a new one: rename the columns that the former
database/schema.sql named differently, drop its triggers, replace its indexes
with those of the models, and create the tables it is missing.

Revision ID: dbb5a7d40e55
Revises:
Create Date: 2026-10-04 00:09:07.723401
"""

from typing import Optional, Sequence, Set, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from liualgotrader.db.models.base import (CurrentTimestamp, RandomUuid,
                                          Timestamp)

# revision identifiers, used by Alembic.
revision: str = "dbb5a7d40e55"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns that the former database/schema.sql named differently.
_RENAMED_COLUMNS = [
    ("accounts", "modified_tstamp", "modify_tstamp"),
    ("algo_run", "algo_name", "strategy_name"),
    ("algo_run", "algo_env", "env"),
    ("algo_run", "ref_algo_run", "ref_algo_run_id"),
    ("portfolio", "size", "portfolio_size"),
    ("portfolio", "assets", "asset_type"),
    ("stock_ohlc", "symbol_id", "stock_ohlc_id"),
    ("trade_analysis", "start_tstamp", "start_time"),
    ("trade_analysis", "end_tstamp", "end_time"),
]


def _adopt_existing_tables() -> Set[str]:
    """Bring the tables of a database created before migrations up to date.

    Rename the columns that the former database/schema.sql named
    differently. On PostgreSQL, also drop its triggers, whose work
    Account.add_transaction and the ORM now do. A new database has no tables,
    so nothing changes.

    Returns
    -------
    Return the names of the tables that the database already has.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table, old, new in _RENAMED_COLUMNS:
        if table in existing and old in {
            column["name"] for column in inspector.get_columns(table)
        }:
            op.alter_column(table, old, new_column_name=new)

    if bind.dialect.name == "postgresql":
        # Account.add_transaction updates the balances, and the ORM sets
        # trade_plan.modify_tstamp.
        if "account_transactions" in existing:
            op.execute(
                "DROP TRIGGER IF EXISTS balance_update "
                "ON account_transactions"
            )
        if "trade_plan" in existing:
            op.execute(
                "DROP TRIGGER IF EXISTS update_trade_plan_modify_tstamp "
                "ON trade_plan"
            )
        op.execute("DROP FUNCTION IF EXISTS update_balance()")
        op.execute("DROP FUNCTION IF EXISTS update_modify_tstamp_action()")
    return existing


def _create_table(
    existing: Set[str], name: str, *elements, indexes=()
) -> None:
    """Create a table and its indexes, unless the database already has it.

    For a table that exists, replace its indexes with the listed ones: drop
    every other index, except one that a constraint uses, and create the
    listed indexes it lacks.

    Parameters
    ----------
    existing: Set[str]
        The names of the tables that the database already has.
    name: str
        The table name.
    *elements
        The columns and constraints of the table, as op.create_table takes
        them.
    indexes, default ()
        The columns that each have an index, named ix_<table>_<column>.
    """
    wanted = {f"ix_{name}_{column}": column for column in indexes}
    present: Set[Optional[str]] = set()
    if name in existing:
        # Keep the indexes of the models and of constraints, and drop the
        # others, which the former schema.sql created under other names.
        for index in sa.inspect(op.get_bind()).get_indexes(name):
            index_name = index["name"]
            if index_name in wanted or index.get("duplicates_constraint"):
                present.add(index_name)
            elif index_name:
                op.drop_index(index_name, table_name=name)
    else:
        op.create_table(name, *elements)
    for index_name, column in wanted.items():
        if index_name not in present:
            op.create_index(op.f(index_name), name, [column])


def upgrade() -> None:
    """Create the schema, or update a database created before migrations."""
    existing = _adopt_existing_tables()
    _create_table(
        existing,
        "accounts",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "balance", sa.Double(), server_default="0.0", nullable=False
        ),
        sa.Column(
            "allow_negative",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "credit_line", sa.Double(), server_default="0.0", nullable=False
        ),
        sa.Column(
            "details",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", Timestamp(timezone=True), nullable=True),
        sa.CheckConstraint("credit_line > 0 OR NOT allow_negative"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    _create_table(
        existing,
        "algo_run",
        sa.Column("algo_run_id", sa.Integer(), nullable=False),
        sa.Column("strategy_name", sa.Text(), nullable=False),
        sa.Column("env", sa.Text(), nullable=False),
        sa.Column("build_number", sa.Text(), nullable=False),
        sa.Column(
            "parameters",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "start_time",
            Timestamp(timezone=False),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("end_time", Timestamp(timezone=False), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("batch_id", sa.Text(), server_default="", nullable=False),
        sa.Column("ref_algo_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ref_algo_run_id"],
            ["algo_run.algo_run_id"],
        ),
        sa.PrimaryKeyConstraint("algo_run_id"),
        indexes=["batch_id", "start_time"],
    )
    _create_table(
        existing,
        "keystore",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    _create_table(
        existing,
        "optimizer_run",
        sa.Column("optimizer_run_id", sa.Integer(), nullable=False),
        sa.Column("optimizer_session_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column(
            "tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("parameters", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("optimizer_run_id"),
        indexes=["optimizer_session_id"],
    )
    _create_table(
        existing,
        "stock_ohlc",
        sa.Column("stock_ohlc_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("symbol_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column(
            "indicators",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("modify_tstamp", Timestamp(timezone=False), nullable=True),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=False),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("stock_ohlc_id"),
        sa.UniqueConstraint("symbol", "symbol_date"),
        indexes=["symbol", "symbol_date"],
    )
    _create_table(
        existing,
        "ticker_data",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "similar_tickers",
            sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("short_ratio", sa.Double(), nullable=True),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=False),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", Timestamp(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
        indexes=["industry", "sector"],
    )
    _create_table(
        existing,
        "trending_tickers",
        sa.Column("trending_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "scanner_name",
            sa.Text(),
            server_default="momentum",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("trending_id"),
        indexes=["batch_id", "create_tstamp", "scanner_name"],
    )
    _create_table(
        existing,
        "account_transactions",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Double(), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.account_id"],
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    _create_table(
        existing,
        "gain_loss",
        sa.Column("gain_loss_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("algo_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "gain_percentage", sa.Numeric(precision=5, scale=2), nullable=False
        ),
        sa.Column(
            "gain_value", sa.Numeric(precision=8, scale=2), nullable=False
        ),
        sa.Column(
            "tstamp",
            Timestamp(timezone=False),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["algo_run_id"],
            ["algo_run.algo_run_id"],
        ),
        sa.PrimaryKeyConstraint("gain_loss_id"),
        sa.UniqueConstraint("symbol", "algo_run_id"),
    )
    _create_table(
        existing,
        "new_trades",
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("algo_run_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column(
            "operation",
            sa.Enum(
                "buy",
                "sell",
                "sell_short",
                "buy_short",
                name="trade_operation",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("qty", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column(
            "indicators",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("client_time", sa.Text(), nullable=True),
        sa.Column(
            "tstamp",
            Timestamp(timezone=False),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "stop_price", sa.Numeric(precision=8, scale=2), nullable=True
        ),
        sa.Column(
            "target_price", sa.Numeric(precision=8, scale=2), nullable=True
        ),
        sa.Column("expire_tstamp", Timestamp(timezone=False), nullable=True),
        sa.Column(
            "trade_fee",
            sa.Numeric(precision=9, scale=2),
            server_default="0.0",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["algo_run_id"],
            ["algo_run.algo_run_id"],
        ),
        sa.PrimaryKeyConstraint("trade_id"),
        indexes=["algo_run_id", "symbol", "tstamp"],
    )
    _create_table(
        existing,
        "portfolio",
        sa.Column("portfolio_id", sa.Text(), nullable=False),
        sa.Column("portfolio_size", sa.Integer(), nullable=False),
        sa.Column(
            "parameters",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("expire_tstamp", Timestamp(timezone=True), nullable=True),
        sa.Column(
            "tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column(
            "asset_type",
            sa.Enum(
                "US_EQUITIES",
                "CRYPTO",
                name="asset_type",
                create_constraint=True,
            ),
            server_default="US_EQUITIES",
            nullable=False,
        ),
        sa.Column("external_account_id", sa.Text(), nullable=True),
        sa.Column("broker", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.account_id"],
        ),
        sa.PrimaryKeyConstraint("portfolio_id"),
        indexes=["account_id"],
    )
    _create_table(
        existing,
        "trade_analysis",
        sa.Column("trade_analysis_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("algo_run_id", sa.Integer(), nullable=False),
        sa.Column("start_time", Timestamp(timezone=True), nullable=False),
        sa.Column("end_time", Timestamp(timezone=True), nullable=False),
        sa.Column(
            "gain_percentage", sa.Numeric(precision=5, scale=2), nullable=False
        ),
        sa.Column(
            "gain_value", sa.Numeric(precision=8, scale=2), nullable=False
        ),
        sa.Column("r_units", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column(
            "tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["algo_run_id"],
            ["algo_run.algo_run_id"],
        ),
        sa.PrimaryKeyConstraint("trade_analysis_id"),
        sa.UniqueConstraint("symbol", "algo_run_id", "start_time"),
    )
    _create_table(
        existing,
        "portfolio_batch_ids",
        sa.Column("assoc_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.portfolio_id"],
        ),
        sa.PrimaryKeyConstraint("assoc_id"),
        indexes=["batch_id", "portfolio_id"],
    )
    _create_table(
        existing,
        "trade_plan",
        sa.Column(
            "trade_plan_id",
            sa.Uuid(),
            server_default=RandomUuid(),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("strategy_name", sa.Text(), nullable=False),
        sa.Column(
            "parameters",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "create_tstamp",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", Timestamp(timezone=True), nullable=True),
        sa.Column("expire_tstamp", Timestamp(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.portfolio_id"],
        ),
        sa.PrimaryKeyConstraint("trade_plan_id"),
    )
    _create_table(
        existing,
        "trade_plan_execution_audit",
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("trade_plan_id", sa.Uuid(), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "started_on",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "ended_on",
            Timestamp(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plan.trade_plan_id"],
        ),
        sa.PrimaryKeyConstraint("execution_id"),
    )


def downgrade() -> None:
    """Drop every table of the schema, and on PostgreSQL its enum types."""
    op.drop_table("trade_plan_execution_audit")
    op.drop_table("trade_plan")
    op.drop_table("portfolio_batch_ids")
    op.drop_table("trade_analysis")
    op.drop_table("portfolio")
    op.drop_table("new_trades")
    op.drop_table("gain_loss")
    op.drop_table("account_transactions")
    op.drop_table("trending_tickers")
    op.drop_table("ticker_data")
    op.drop_table("stock_ohlc")
    op.drop_table("optimizer_run")
    op.drop_table("keystore")
    op.drop_table("algo_run")
    op.drop_table("accounts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS trade_operation")
        op.execute("DROP TYPE IF EXISTS asset_type")
