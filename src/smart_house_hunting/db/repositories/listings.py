from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from smart_house_hunting.db.models import (
    Listing,
    ListingState,
    Property,
    PropertyAlias,
    ScanJob,
    ScanObservation,
)


@dataclass(frozen=True)
class ListingStateInput:
    status: str | None = None
    price: Decimal | None = None
    bedrooms: Decimal | None = None
    bathrooms: Decimal | None = None
    living_area_sqft: int | None = None
    lot_size_sqft: Decimal | None = None
    property_tax_annual: Decimal | None = None
    hoa_monthly: Decimal | None = None
    description: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    source_updated_at: datetime | None = None

    def fingerprint(self) -> str:
        def default(value: object) -> str:
            if isinstance(value, (datetime, Decimal)):
                return str(value)
            raise TypeError(f"Unsupported listing-state value: {type(value).__name__}")

        encoded = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), default=default
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def get_or_create_property(
    session: Session,
    *,
    alias_kind: str,
    alias_value: str,
    street_address: str,
    municipality: str,
    unit_number: str | None = None,
    postal_code: str | None = None,
    parcel_id: str | None = None,
) -> tuple[Property, bool]:
    existing_alias = session.scalar(
        select(PropertyAlias).where(
            PropertyAlias.kind == alias_kind,
            PropertyAlias.normalized_value == alias_value,
        )
    )
    if existing_alias is not None:
        return existing_alias.property, False

    property_record = Property(
        street_address=street_address,
        unit_number=unit_number,
        municipality=municipality,
        postal_code=postal_code,
        parcel_id=parcel_id,
    )
    property_record.aliases.append(
        PropertyAlias(
            kind=alias_kind,
            normalized_value=alias_value,
            confidence=100,
        )
    )
    session.add(property_record)
    session.flush()
    return property_record, True


def get_or_create_listing(
    session: Session,
    *,
    property_record: Property,
    source: str,
    source_listing_id: str,
    episode_key: str,
    url: str,
    observed_at: datetime,
) -> tuple[Listing, bool]:
    listing = session.scalar(
        select(Listing).where(
            Listing.source == source,
            Listing.source_listing_id == source_listing_id,
            Listing.episode_key == episode_key,
        )
    )
    if listing is not None:
        existing_seen = listing.last_seen_at
        if existing_seen.tzinfo is None:
            existing_seen = existing_seen.replace(tzinfo=UTC)
        comparable_observed = (
            observed_at.replace(tzinfo=UTC) if observed_at.tzinfo is None else observed_at
        )
        if comparable_observed > existing_seen:
            listing.last_seen_at = observed_at
        if listing.url != url:
            listing.url = url
        return listing, False

    listing = Listing(
        property=property_record,
        source=source,
        source_listing_id=source_listing_id,
        episode_key=episode_key,
        url=url,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    session.add(listing)
    session.flush()
    return listing, True


def get_or_create_listing_state(
    session: Session, *, listing: Listing, state: ListingStateInput
) -> tuple[ListingState, bool]:
    content_hash = state.fingerprint()
    existing = session.scalar(
        select(ListingState).where(
            ListingState.listing_id == listing.id,
            ListingState.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False

    listing_state = ListingState(
        listing=listing,
        content_hash=content_hash,
        **asdict(state),
    )
    session.add(listing_state)
    session.flush()
    return listing_state, True


def record_observation(
    session: Session,
    *,
    scan_job: ScanJob,
    listing: Listing,
    listing_state: ListingState,
    observed_at: datetime,
) -> tuple[ScanObservation, bool]:
    existing = session.scalar(
        select(ScanObservation).where(
            ScanObservation.scan_job_id == scan_job.id,
            ScanObservation.listing_id == listing.id,
        )
    )
    if existing is not None:
        if existing.listing_state_id != listing_state.id:
            raise ValueError("A scan cannot observe two states for the same listing")
        return existing, False

    observation = ScanObservation(
        scan_job=scan_job,
        listing=listing,
        listing_state=listing_state,
        observed_at=observed_at,
    )
    session.add(observation)
    session.flush()
    return observation, True
