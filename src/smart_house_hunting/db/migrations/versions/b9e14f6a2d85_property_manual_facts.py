"""property manual facts

Revision ID: b9e14f6a2d85
Revises: a8d93e5f7c14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e14f6a2d85"
down_revision: str | Sequence[str] | None = "a8d93e5f7c14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("manual_facts", sa.JSON(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("properties", "manual_facts")
