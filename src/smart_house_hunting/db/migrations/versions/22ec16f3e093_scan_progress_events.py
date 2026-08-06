"""scan progress events

Revision ID: 22ec16f3e093
Revises: 999e7248e7bc
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "22ec16f3e093"
down_revision: str | Sequence[str] | None = "999e7248e7bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_progress_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_job_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scan_job_id"],
            ["scan_jobs.id"],
            name=op.f("fk_scan_progress_events_scan_job_id_scan_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_progress_events")),
    )
    with op.batch_alter_table("scan_progress_events", schema=None) as batch_op:
        batch_op.create_index("ix_scan_progress_events_job_id", ["scan_job_id", "id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("scan_progress_events", schema=None) as batch_op:
        batch_op.drop_index("ix_scan_progress_events_job_id")
    op.drop_table("scan_progress_events")
