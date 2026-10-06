"""Initial schema.

Create the tables of a new database.

Revision ID: dbb5a7d40e55
Revises:
Create Date: 2026-10-04 00:09:07.723401
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from liualgotrader.db.models.base import CurrentTimestamp, RandomUuid

# revision identifiers, used by Alembic.
revision: str = "dbb5a7d40e55"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_table(name: str, *elements, indexes=()) -> None:
    """Create a table and its indexes.

    Parameters
    ----------
    name: str
        The table name.
    *elements
        The columns and constraints of the table, as op.create_table takes
        them.
    indexes, default ()
        The columns that each have an index, named ix_<table>_<column>.
    """
    op.create_table(name, *elements)
    for column in indexes:
        op.create_index(op.f(f"ix_{name}_{column}"), name, [column])


def upgrade() -> None:
    """Create the schema."""
    _create_table(
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("credit_line > 0 OR NOT allow_negative"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    _create_table(
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
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
        "keystore",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "tstamp",
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    _create_table(
        "optimizer_run",
        sa.Column("optimizer_run_id", sa.Integer(), nullable=False),
        sa.Column("optimizer_session_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column(
            "tstamp",
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("parameters", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("optimizer_run_id"),
        indexes=["optimizer_session_id"],
    )
    _create_table(
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
        sa.Column("modify_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "create_tstamp",
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("stock_ohlc_id"),
        sa.UniqueConstraint("symbol", "symbol_date"),
        indexes=["symbol", "symbol_date"],
    )
    _create_table(
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
        indexes=["industry", "sector"],
    )
    _create_table(
        "trending_tickers",
        sa.Column("trending_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column(
            "create_tstamp",
            sa.DateTime(timezone=True),
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "create_tstamp",
            sa.DateTime(timezone=True),
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
            sa.DateTime(timezone=True),
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
        sa.Column("client_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tstamp",
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "stop_price", sa.Numeric(precision=8, scale=2), nullable=True
        ),
        sa.Column(
            "target_price", sa.Numeric(precision=8, scale=2), nullable=True
        ),
        sa.Column("expire_tstamp", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("expire_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tstamp",
            sa.DateTime(timezone=True),
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
        "trade_analysis",
        sa.Column("trade_analysis_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("algo_run_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "gain_percentage", sa.Numeric(precision=5, scale=2), nullable=False
        ),
        sa.Column(
            "gain_value", sa.Numeric(precision=8, scale=2), nullable=False
        ),
        sa.Column("r_units", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column(
            "tstamp",
            sa.DateTime(timezone=True),
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column("modify_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expire_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.portfolio_id"],
        ),
        sa.PrimaryKeyConstraint("trade_plan_id"),
    )
    _create_table(
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
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.Column(
            "ended_on",
            sa.DateTime(timezone=True),
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
