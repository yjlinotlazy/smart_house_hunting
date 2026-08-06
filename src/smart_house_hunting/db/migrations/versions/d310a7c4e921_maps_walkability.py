"""maps and walkability

Revision ID: d310a7c4e921
Revises: c2a14f6e8b32
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d310a7c4e921"
down_revision: str | Sequence[str] | None = "c2a14f6e8b32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("google_place_id", sa.String(300), nullable=False, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("primary_type", sa.String(100)),
        sa.Column("types", sa.JSON(), nullable=False),
        sa.Column("formatted_address", sa.Text()),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("google_maps_uri", sa.Text()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "nearby_analysis_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("property_ids", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "nearby_search_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("property_id", "category", name="uq_nearby_property_category"),
    )
    op.create_table(
        "property_walking_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "place_id", sa.Integer(), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("distance_meters", sa.Integer()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("route_status", sa.String(30), nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "property_id", "place_id", "category", name="uq_property_place_category"
        ),
    )


def downgrade() -> None:
    op.drop_table("property_walking_routes")
    op.drop_table("nearby_search_cache")
    op.drop_table("nearby_analysis_runs")
    op.drop_table("places")
