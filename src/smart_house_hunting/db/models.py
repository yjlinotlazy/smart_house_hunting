from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Property(TimestampMixin, Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint("state = 'MA'", name="massachusetts_only"),
        Index("ix_properties_municipality", "municipality"),
        Index("ix_properties_parcel", "municipality", "parcel_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    street_address: Mapped[str] = mapped_column(String(300), nullable=False)
    unit_number: Mapped[str | None] = mapped_column(String(100))
    municipality: Mapped[str] = mapped_column(String(150), nullable=False)
    state: Mapped[str] = mapped_column(String(2), default="MA", server_default="MA")
    postal_code: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    parcel_id: Mapped[str | None] = mapped_column(String(200))
    manual_tags: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]", nullable=False
    )
    manual_tag_categories: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    manual_facts: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )

    aliases: Mapped[list[PropertyAlias]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    listings: Mapped[list[Listing]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )


class PropertyAlias(Base):
    __tablename__ = "property_aliases"
    __table_args__ = (
        UniqueConstraint("kind", "normalized_value", name="uq_property_alias_identity"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_percentage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    property: Mapped[Property] = relationship(back_populates="aliases")


class PropertyDuplicateCandidate(Base):
    __tablename__ = "property_duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("property_low_id", "property_high_id", name="uq_property_duplicate_pair"),
        CheckConstraint("property_low_id < property_high_id", name="ordered_pair"),
        CheckConstraint("status IN ('possible','dismissed','merged')", name="valid_status"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_low_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_high_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="possible", server_default="possible", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Listing(TimestampMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_listing_id", "episode_key", name="uq_listing_source_episode"
        ),
        Index("ix_listings_property_source", "property_id", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_listing_id: Mapped[str] = mapped_column(String(200), nullable=False)
    episode_key: Mapped[str] = mapped_column(
        String(200), default="initial", server_default="initial"
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    property: Mapped[Property] = relationship(back_populates="listings")
    states: Mapped[list[ListingState]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class ListingState(Base):
    __tablename__ = "listing_states"
    __table_args__ = (
        UniqueConstraint("listing_id", "content_hash", name="uq_listing_state_content"),
        Index("ix_listing_states_listing_created", "listing_id", "created_at"),
        CheckConstraint("price IS NULL OR price >= 0", name="nonnegative_price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    bedrooms: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    living_area_sqft: Mapped[int | None] = mapped_column(Integer)
    lot_size_sqft: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    property_tax_annual: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    hoa_monthly: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    listing: Mapped[Listing] = relationship(back_populates="states")


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','partial_success','success','failed','interrupted')",
            name="valid_status",
        ),
        Index("ix_scan_jobs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued")
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)

    source_runs: Mapped[list[ScanSourceRun]] = relationship(
        back_populates="scan_job", cascade="all, delete-orphan"
    )
    observations: Mapped[list[ScanObservation]] = relationship(
        back_populates="scan_job", cascade="all, delete-orphan"
    )
    progress_events: Mapped[list[ScanProgressEvent]] = relationship(
        back_populates="scan_job", cascade="all, delete-orphan"
    )


class ScanSourceRun(Base):
    __tablename__ = "scan_source_runs"
    __table_args__ = (
        UniqueConstraint("scan_job_id", "source", name="uq_scan_source_run"),
        CheckConstraint(
            "status IN "
            "('queued','running','success','partial_failed','failed','blocked','skipped')",
            name="valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_job_id: Mapped[int] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued")
    parser_version: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)

    scan_job: Mapped[ScanJob] = relationship(back_populates="source_runs")


class ScanProgressEvent(Base):
    __tablename__ = "scan_progress_events"
    __table_args__ = (Index("ix_scan_progress_events_job_id", "scan_job_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_job_id: Mapped[int] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scan_job: Mapped[ScanJob] = relationship(back_populates="progress_events")


class ScanObservation(Base):
    __tablename__ = "scan_observations"
    __table_args__ = (
        UniqueConstraint("scan_job_id", "listing_id", name="uq_scan_listing_observation"),
        Index("ix_scan_observations_state", "listing_state_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_job_id: Mapped[int] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    listing_state_id: Mapped[int] = mapped_column(
        ForeignKey("listing_states.id", ondelete="RESTRICT"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scan_job: Mapped[ScanJob] = relationship(back_populates="observations")
    listing: Mapped[Listing] = relationship()
    listing_state: Mapped[ListingState] = relationship()


class PropertyEvent(Base):
    __tablename__ = "property_events"
    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_property_event_fingerprint"),
        Index("ix_property_events_property_occurred", "property_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SoldComparable(Base):
    __tablename__ = "sold_comparables"
    __table_args__ = (
        UniqueConstraint(
            "candidate_property_id",
            "source",
            "source_record_id",
            name="uq_candidate_source_comparable",
        ),
        CheckConstraint("sale_price IS NULL OR sale_price >= 0", name="nonnegative_sale_price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sold_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    sale_date: Mapped[date | None] = mapped_column(Date)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    original_listing_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    final_listing_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    distance_miles: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    similarity: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (
        CheckConstraint(
            "criteria_status IN ('missing','pending','ready','failed')",
            name="valid_criteria_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    criteria_status: Mapped[str] = mapped_column(
        String(20), default="missing", server_default="missing"
    )
    criteria: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LLMRun(Base):
    __tablename__ = "llm_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','partial_success','success','failed','interrupted')",
            name="valid_status",
        ),
        Index("ix_llm_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued")
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    force: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)


class LLMEvaluation(Base):
    __tablename__ = "llm_evaluations"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','success','failed')", name="valid_status"),
        Index(
            "ix_llm_evaluation_cache",
            "property_id",
            "profile_hash",
            "property_data_hash",
            "provider",
            "model",
            "prompt_version",
        ),
        Index("ix_llm_evaluation_current", "property_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    llm_run_id: Mapped[int] = mapped_column(
        ForeignKey("llm_runs.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    profile_hash: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.profile_hash", ondelete="RESTRICT"), nullable=False
    )
    property_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    structured_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evaluation_text: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[list[Any] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LLMDigest(Base):
    __tablename__ = "llm_digests"
    __table_args__ = (
        CheckConstraint("status IN ('success','failed')", name="valid_status"),
        Index(
            "ix_llm_digest_cache",
            "input_hash",
            "provider",
            "model",
            "prompt_version",
        ),
        Index("ix_llm_digest_current", "is_current"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    llm_run_id: Mapped[int] = mapped_column(
        ForeignKey("llm_runs.id", ondelete="CASCADE"), nullable=False
    )
    profile_hash: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.profile_hash", ondelete="RESTRICT"), nullable=False
    )
    property_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    structured_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_place_id: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    primary_type: Mapped[str | None] = mapped_column(String(100))
    types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    formatted_address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    google_maps_uri: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NearbyAnalysisRun(Base):
    __tablename__ = "nearby_analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    property_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    force: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NearbySearchCache(Base):
    __tablename__ = "nearby_search_cache"
    __table_args__ = (
        UniqueConstraint("property_id", "category", name="uq_nearby_property_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PropertyWalkingRoute(Base):
    __tablename__ = "property_walking_routes"
    __table_args__ = (
        UniqueConstraint("property_id", "place_id", "category", name="uq_property_place_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    route_status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
