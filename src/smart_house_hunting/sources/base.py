from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NormalizedListing(StrictModel):
    source: str
    source_listing_id: str
    url: str
    street_address: str
    unit_number: str | None = None
    municipality: str
    state: str = "MA"
    postal_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    parcel_id: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    status: str | None = None
    bedrooms: Decimal | None = Field(default=None, ge=0)
    bathrooms: Decimal | None = Field(default=None, ge=0)
    living_area_sqft: int | None = Field(default=None, ge=0)
    lot_size_sqft: Decimal | None = Field(default=None, ge=0)
    property_tax_annual: Decimal | None = Field(default=None, ge=0)
    hoa_monthly: Decimal | None = Field(default=None, ge=0)
    description: str | None = None
    facts: dict[str, object] = Field(default_factory=dict)
    source_updated_at: datetime | None = None
    last_observed_at: datetime | None = None


class ScanRequest(StrictModel):
    municipalities: list[str]
    state: str = "MA"
    included_property_types: list[str] = Field(default_factory=lambda: ["single_family"])
    minimum_bedrooms: Decimal = Field(default=Decimal(0), ge=0)
    minimum_bathrooms: Decimal = Field(default=Decimal(0), ge=0)
    maximum_price: Decimal = Field(gt=0)
    tracked_listings: list[NormalizedListing] = Field(default_factory=list)
    retain_source_payloads: bool = False
    force_refresh: bool = False


def missing_required_fields(listing: NormalizedListing) -> tuple[str, ...]:
    missing = [
        name
        for name in (
            "bedrooms",
            "bathrooms",
            "price",
            "lot_size_sqft",
            "living_area_sqft",
            "status",
        )
        if getattr(listing, name) is None or getattr(listing, name) == ""
    ]
    if listing.facts.get("year_built") in (None, ""):
        missing.append("year_built")
    images = listing.facts.get("image_urls")
    has_image = (
        (isinstance(images, str) and bool(images.strip()))
        or (
            isinstance(images, list)
            and any(isinstance(image, str) and image.strip() for image in images)
        )
        or (
            isinstance(listing.facts.get("image_url"), str)
            and bool(listing.facts["image_url"].strip())
        )
    )
    if not has_image:
        missing.append("image")
    return tuple(missing)


def detail_completed_today(listing: NormalizedListing) -> bool:
    observed = listing.last_observed_at
    if observed is None or listing.facts.get("detail_error") or missing_required_fields(listing):
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone().date() == datetime.now().astimezone().date()


def merge_missing_listing(
    current: NormalizedListing, previous: NormalizedListing
) -> NormalizedListing:
    fields = (
        "unit_number",
        "postal_code",
        "latitude",
        "longitude",
        "parcel_id",
        "price",
        "status",
        "bedrooms",
        "bathrooms",
        "living_area_sqft",
        "lot_size_sqft",
        "property_tax_annual",
        "hoa_monthly",
        "description",
        "source_updated_at",
        "last_observed_at",
    )
    updates = {
        field: getattr(previous, field)
        for field in fields
        if getattr(current, field) is None or getattr(current, field) == ""
    }
    facts = dict(previous.facts)
    if "detail_error" not in current.facts:
        facts.pop("detail_error", None)
    if current.status != "unavailable":
        facts.pop("unavailable_reason", None)
    for key, value in current.facts.items():
        if value is not None and value != "" and value != [] and value != {}:
            facts[key] = value
    updates["facts"] = facts
    return current.model_copy(update=updates)


ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]]
CandidateCallback = Callable[[NormalizedListing], Awaitable[None]]


class SourceAdapter(Protocol):
    name: str
    parser_version: str

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]: ...
