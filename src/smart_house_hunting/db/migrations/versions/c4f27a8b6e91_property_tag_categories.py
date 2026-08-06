"""property tag categories

Revision ID: c4f27a8b6e91
Revises: b9e14f6a2d85
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f27a8b6e91"
down_revision: str | Sequence[str] | None = "b9e14f6a2d85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("manual_tag_categories", sa.JSON(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("properties", "manual_tag_categories")
