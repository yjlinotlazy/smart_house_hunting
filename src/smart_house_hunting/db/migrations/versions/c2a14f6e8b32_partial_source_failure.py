"""partial source failure

Revision ID: c2a14f6e8b32
Revises: b1f03e5d9a21
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2a14f6e8b32"
down_revision: str | Sequence[str] | None = "b1f03e5d9a21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_STATUSES = (
    "status IN ('queued','running','success','partial_failed','failed','blocked','skipped')"
)
_OLD_STATUSES = "status IN ('queued','running','success','failed','blocked','skipped')"


def upgrade() -> None:
    with op.batch_alter_table("scan_source_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_scan_source_runs_valid_status"), type_="check")
        batch_op.create_check_constraint(op.f("ck_scan_source_runs_valid_status"), _NEW_STATUSES)
    op.execute(
        "UPDATE scan_source_runs SET status = 'partial_failed' "
        "WHERE status = 'failed' "
        "AND COALESCE(json_extract(counters, '$.candidates'), 0) > 0"
    )


def downgrade() -> None:
    op.execute("UPDATE scan_source_runs SET status = 'failed' WHERE status = 'partial_failed'")
    with op.batch_alter_table("scan_source_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_scan_source_runs_valid_status"), type_="check")
        batch_op.create_check_constraint(op.f("ck_scan_source_runs_valid_status"), _OLD_STATUSES)
