"""Add the score of an optimizer run.

Backtests no longer write trades to the database, so the optimizer records
the score of each run with it.

Revision ID: 5c1f0e9a7b3d
Revises: dbb5a7d40e55
Create Date: 2026-10-31 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1f0e9a7b3d"
down_revision: Union[str, Sequence[str], None] = "dbb5a7d40e55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the score column to optimizer_run."""
    op.add_column(
        "optimizer_run", sa.Column("score", sa.Double(), nullable=True)
    )


def downgrade() -> None:
    """Drop the score column of optimizer_run."""
    with op.batch_alter_table("optimizer_run") as batch_op:
        batch_op.drop_column("score")
