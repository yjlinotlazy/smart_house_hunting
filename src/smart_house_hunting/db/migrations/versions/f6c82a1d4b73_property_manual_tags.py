"""property manual tags

Revision ID: f6c82a1d4b73
Revises: e4b71d9c2a60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6c82a1d4b73"
down_revision: str | Sequence[str] | None = "e4b71d9c2a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("manual_tags", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("properties", "manual_tags")
