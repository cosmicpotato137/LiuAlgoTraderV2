"""Drop the unused tables.

The stock_ohlc and trade_plan_execution_audit tables no longer have models,
and nothing reads or writes them.

Revision ID: 6f29b850505b
Revises: 5c1f0e9a7b3d
Create Date: 2026-11-08 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from liualgotrader.db.models.base import CurrentTimestamp

# revision identifiers, used by Alembic.
revision: str = "6f29b850505b"
down_revision: Union[str, Sequence[str], None] = "5c1f0e9a7b3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the stock_ohlc and trade_plan_execution_audit tables."""
    op.drop_table("trade_plan_execution_audit")
    op.drop_table("stock_ohlc")


def downgrade() -> None:
    """Create the dropped tables again, empty."""
    json = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()), "postgresql"
    )
    op.create_table(
        "stock_ohlc",
        sa.Column("stock_ohlc_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("symbol_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("indicators", json, nullable=True),
        sa.Column("modify_tstamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "create_tstamp",
            sa.DateTime(timezone=True),
            server_default=CurrentTimestamp(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("stock_ohlc_id"),
        sa.UniqueConstraint("symbol", "symbol_date"),
    )
    for column in ("symbol", "symbol_date"):
        op.create_index(
            op.f(f"ix_stock_ohlc_{column}"), "stock_ohlc", [column]
        )
    op.create_table(
        "trade_plan_execution_audit",
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("trade_plan_id", sa.Uuid(), nullable=True),
        sa.Column("details", json, nullable=True),
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
