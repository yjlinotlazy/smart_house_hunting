from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from smart_house_hunting.db.models import (
    Listing,
    ListingState,
    Property,
    PropertyAlias,
    PropertyDuplicateCandidate,
    ScanJob,
)
from smart_house_hunting.db.repositories import (
    ListingStateInput,
    get_or_create_listing,
    get_or_create_listing_state,
    record_observation,
)
from smart_house_hunting.normalization import normalize_address, normalize_municipality
from smart_house_hunting.services.history import derive_listing_events
from smart_house_hunting.sources import NormalizedListing


@dataclass
class IngestCounters:
    candidates: int = 0
    properties_created: int = 0
    listings_created: int = 0
    states_created: int = 0
    observations_created: int = 0
    events_created: int = 0

    def add(self, other: IngestCounters) -> None:
        self.candidates += other.candidates
        self.properties_created += other.properties_created
        self.listings_created += other.listings_created
        self.states_created += other.states_created
        self.observations_created += other.observations_created
        self.events_created += other.events_created

    def as_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "properties_created": self.properties_created,
            "listings_created": self.listings_created,
            "states_created": self.states_created,
            "observations_created": self.observations_created,
            "events_created": self.events_created,
        }


def _address_alias(municipality: str, street_key: str, unit: str | None) -> str:
    return f"{municipality.casefold()}|{street_key}|{unit or ''}"


def _parcel_alias(municipality: str, parcel_id: str) -> str:
    return f"{municipality.casefold()}|{parcel_id.strip().casefold()}"


def _alias_property(session: Session, kind: str, value: str) -> Property | None:
    alias = session.scalar(
        select(PropertyAlias).where(
            PropertyAlias.kind == kind,
            PropertyAlias.normalized_value == value,
        )
    )
    return alias.property if alias else None


def _street_number(value: str) -> str | None:
    first = value.split(maxsplit=1)[0]
    return first if any(character.isdigit() for character in first) else None


def _distance_meters(
    first_latitude: Decimal,
    first_longitude: Decimal,
    second_latitude: Decimal,
    second_longitude: Decimal,
) -> float:
    latitude_one = math.radians(float(first_latitude))
    latitude_two = math.radians(float(second_latitude))
    delta_latitude = latitude_two - latitude_one
    delta_longitude = math.radians(float(second_longitude - first_longitude))
    value = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_one) * math.cos(latitude_two) * math.sin(delta_longitude / 2) ** 2
    )
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _high_confidence_match(
    session: Session,
    candidate: NormalizedListing,
    municipality: str,
    street_key: str,
    unit: str | None,
) -> Property | None:
    if candidate.latitude is None or candidate.longitude is None:
        return None
    number = _street_number(street_key)
    if number is None:
        return None
    properties = session.scalars(
        select(Property).where(
            Property.municipality == municipality,
            Property.latitude.is_not(None),
            Property.longitude.is_not(None),
        )
    ).all()
    matches: list[Property] = []
    for property_record in properties:
        existing_address = normalize_address(
            property_record.street_address, property_record.unit_number
        )
        if existing_address.unit != unit or _street_number(existing_address.street_key) != number:
            continue
        distance = _distance_meters(
            candidate.latitude,
            candidate.longitude,
            property_record.latitude,
            property_record.longitude,
        )
        if distance > 8:
            continue
        latest_state = session.scalar(
            select(ListingState)
            .join(Listing)
            .where(Listing.property_id == property_record.id)
            .order_by(ListingState.created_at.desc(), ListingState.id.desc())
        )
        if latest_state is None:
            continue
        existing_type = latest_state.facts.get("property_type")
        candidate_type = candidate.facts.get("property_type")
        if existing_type and candidate_type and existing_type != candidate_type:
            continue
        if (
            latest_state.living_area_sqft
            and candidate.living_area_sqft
            and abs(latest_state.living_area_sqft - candidate.living_area_sqft)
            / latest_state.living_area_sqft
            > 0.05
        ):
            continue
        matches.append(property_record)
    return matches[0] if len(matches) == 1 else None


def _record_possible_duplicate(
    session: Session, first: Property, second: Property, reason: str, confidence: int
) -> None:
    if first.id == second.id:
        return
    low, high = sorted((first.id, second.id))
    existing = session.scalar(
        select(PropertyDuplicateCandidate).where(
            PropertyDuplicateCandidate.property_low_id == low,
            PropertyDuplicateCandidate.property_high_id == high,
        )
    )
    if existing is None:
        session.add(
            PropertyDuplicateCandidate(
                property_low_id=low,
                property_high_id=high,
                reason=reason,
                confidence=confidence,
            )
        )


def _add_alias(
    session: Session, property_record: Property, kind: str, value: str, source: str
) -> None:
    existing = session.scalar(
        select(PropertyAlias).where(
            PropertyAlias.kind == kind,
            PropertyAlias.normalized_value == value,
        )
    )
    if existing is None:
        property_record.aliases.append(
            PropertyAlias(
                kind=kind,
                normalized_value=value,
                source=source,
                confidence=100,
            )
        )
    elif existing.property_id != property_record.id:
        _record_possible_duplicate(
            session,
            property_record,
            existing.property,
            f"conflicting {kind} identity",
            90,
        )


def ingest_candidate(
    session: Session,
    *,
    scan_job: ScanJob,
    candidate: NormalizedListing,
    configured_municipalities: list[str],
    observed_at: datetime,
) -> IngestCounters:
    counters = IngestCounters(candidates=1)
    municipality = normalize_municipality(candidate.municipality, configured_municipalities)
    address = normalize_address(candidate.street_address, candidate.unit_number)
    address_value = _address_alias(municipality, address.street_key, address.unit)
    parcel_value = _parcel_alias(municipality, candidate.parcel_id) if candidate.parcel_id else None

    existing_listing = session.scalar(
        select(Listing).where(
            Listing.source == candidate.source,
            Listing.source_listing_id == candidate.source_listing_id,
            Listing.episode_key == "initial",
        )
    )
    property_record = existing_listing.property if existing_listing else None
    parcel_property = _alias_property(session, "parcel", parcel_value) if parcel_value else None
    address_property = _alias_property(session, "address", address_value)
    conflicting_parcel_property = None
    if parcel_property is not None:
        parcel_unit = normalize_address(
            parcel_property.street_address, parcel_property.unit_number
        ).unit
        if parcel_unit != address.unit:
            conflicting_parcel_property = parcel_property
            parcel_property = None
    if property_record is None:
        property_record = parcel_property or address_property
    if parcel_property and address_property and parcel_property.id != address_property.id:
        _record_possible_duplicate(
            session,
            parcel_property,
            address_property,
            "parcel and address identities disagree",
            95,
        )
    if property_record is None:
        property_record = _high_confidence_match(
            session,
            candidate,
            municipality,
            address.street_key,
            address.unit,
        )
    if property_record is None:
        property_record = Property(
            street_address=address.street_display,
            unit_number=address.unit,
            municipality=municipality,
            state="MA",
            postal_code=candidate.postal_code,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            parcel_id=candidate.parcel_id,
        )
        session.add(property_record)
        session.flush()
        counters.properties_created += 1

    if conflicting_parcel_property is not None:
        _record_possible_duplicate(
            session,
            property_record,
            conflicting_parcel_property,
            "shared parcel with different or missing unit evidence",
            70,
        )

    _add_alias(session, property_record, "address", address_value, candidate.source)
    if parcel_value:
        _add_alias(session, property_record, "parcel", parcel_value, candidate.source)
    if property_record.latitude is None and candidate.latitude is not None:
        property_record.latitude = candidate.latitude
        property_record.longitude = candidate.longitude
    if property_record.parcel_id is None and candidate.parcel_id:
        property_record.parcel_id = candidate.parcel_id

    base_address = address_value.rsplit("|", 1)[0]
    similar_aliases = session.scalars(
        select(PropertyAlias).where(
            PropertyAlias.kind == "address",
            PropertyAlias.normalized_value.like(f"{base_address}|%"),
            PropertyAlias.property_id != property_record.id,
        )
    ).all()
    for alias in similar_aliases:
        other_unit = alias.normalized_value.rsplit("|", 1)[1] or None
        if address.unit is None or other_unit is None:
            _record_possible_duplicate(
                session,
                property_record,
                alias.property,
                "same address with missing unit evidence",
                60,
            )

    listing, listing_created = get_or_create_listing(
        session,
        property_record=property_record,
        source=candidate.source,
        source_listing_id=candidate.source_listing_id,
        episode_key="initial",
        url=candidate.url,
        observed_at=observed_at,
    )
    counters.listings_created += int(listing_created)
    previous_state = session.scalar(
        select(ListingState)
        .where(ListingState.listing_id == listing.id)
        .order_by(ListingState.created_at.desc(), ListingState.id.desc())
    )
    state, state_created = get_or_create_listing_state(
        session,
        listing=listing,
        state=ListingStateInput(
            status=candidate.status,
            price=candidate.price,
            bedrooms=candidate.bedrooms,
            bathrooms=candidate.bathrooms,
            living_area_sqft=candidate.living_area_sqft,
            lot_size_sqft=candidate.lot_size_sqft,
            property_tax_annual=candidate.property_tax_annual,
            hoa_monthly=candidate.hoa_monthly,
            description=candidate.description,
            facts=candidate.facts,
            source_updated_at=candidate.source_updated_at,
        ),
    )
    counters.states_created += int(state_created)
    _, observation_created = record_observation(
        session,
        scan_job=scan_job,
        listing=listing,
        listing_state=state,
        observed_at=observed_at,
    )
    counters.observations_created += int(observation_created)
    counters.events_created += derive_listing_events(
        session,
        property_record=property_record,
        listing=listing,
        current_state=state,
        previous_state=previous_state,
        listing_created=listing_created,
        observed_at=observed_at,
    )
    return counters
