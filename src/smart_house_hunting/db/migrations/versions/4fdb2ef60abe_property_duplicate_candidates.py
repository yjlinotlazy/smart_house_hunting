"""property duplicate candidates

Revision ID: 4fdb2ef60abe
Revises: 22ec16f3e093
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4fdb2ef60abe"
down_revision: str | Sequence[str] | None = "22ec16f3e093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "property_duplicate_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_low_id", sa.Integer(), nullable=False),
        sa.Column("property_high_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="possible", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "property_low_id < property_high_id",
            name=op.f("ck_property_duplicate_candidates_ordered_pair"),
        ),
        sa.CheckConstraint(
            "status IN ('possible','dismissed','merged')",
            name=op.f("ck_property_duplicate_candidates_valid_status"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name=op.f("ck_property_duplicate_candidates_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["property_high_id"],
            ["properties.id"],
            name=op.f("fk_property_duplicate_candidates_property_high_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["property_low_id"],
            ["properties.id"],
            name=op.f("fk_property_duplicate_candidates_property_low_id_properties"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_duplicate_candidates")),
        sa.UniqueConstraint(
            "property_low_id",
            "property_high_id",
            name="uq_property_duplicate_pair",
        ),
    )
    with op.batch_alter_table("property_duplicate_candidates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_property_duplicate_candidates_property_high_id"),
            ["property_high_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_property_duplicate_candidates_property_low_id"),
            ["property_low_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("property_duplicate_candidates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_property_duplicate_candidates_property_low_id"))
        batch_op.drop_index(batch_op.f("ix_property_duplicate_candidates_property_high_id"))
    op.drop_table("property_duplicate_candidates")
