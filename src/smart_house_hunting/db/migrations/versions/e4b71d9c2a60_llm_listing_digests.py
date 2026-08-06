"""LLM listing digests

Revision ID: e4b71d9c2a60
Revises: d310a7c4e921
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b71d9c2a60"
down_revision: str | Sequence[str] | None = "d310a7c4e921"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "llm_run_id",
            sa.Integer(),
            sa.ForeignKey("llm_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_hash",
            sa.String(64),
            sa.ForeignKey("profile_versions.profile_hash", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("property_ids", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("structured_result", sa.JSON()),
        sa.Column("error_summary", sa.Text()),
        sa.Column("is_current", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('success','failed')", name="valid_status"),
    )
    op.create_index(
        "ix_llm_digest_cache",
        "llm_digests",
        ["input_hash", "provider", "model", "prompt_version"],
    )
    op.create_index("ix_llm_digest_current", "llm_digests", ["is_current"])


def downgrade() -> None:
    op.drop_index("ix_llm_digest_current", table_name="llm_digests")
    op.drop_index("ix_llm_digest_cache", table_name="llm_digests")
    op.drop_table("llm_digests")
