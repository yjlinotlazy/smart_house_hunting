"""normalize legacy manual tag names

Revision ID: a8d93e5f7c14
Revises: f6c82a1d4b73
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d93e5f7c14"
down_revision: str | Sequence[str] | None = "f6c82a1d4b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE properties SET manual_tags = "
            "replace(replace(replace(manual_tags, "
            "'\"double_yellow\"', '\"双黄线\"'), "
            "'\"corner_lot\"', '\"Corner lot\"'), "
            "'\"scissors_sha\"', '\"剪刀煞\"')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE properties SET manual_tags = "
            "replace(replace(replace(manual_tags, "
            "'\"双黄线\"', '\"double_yellow\"'), "
            "'\"Corner lot\"', '\"corner_lot\"'), "
            "'\"剪刀煞\"', '\"scissors_sha\"')"
        )
    )
