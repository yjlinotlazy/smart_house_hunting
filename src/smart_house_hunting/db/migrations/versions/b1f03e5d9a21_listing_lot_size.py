"""listing lot size

Revision ID: b1f03e5d9a21
Revises: 4fdb2ef60abe
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f03e5d9a21"
down_revision: str | Sequence[str] | None = "4fdb2ef60abe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "listing_states",
        sa.Column("lot_size_sqft", sa.Numeric(precision=14, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("listing_states", "lot_size_sqft")
