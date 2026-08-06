from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from smart_house_hunting.db.models import (
    Listing,
    ListingState,
    Property,
    PropertyEvent,
    ScanObservation,
)
from smart_house_hunting.properties.models import PropertyEventView, PropertyHistoryResponse


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fingerprint(
    listing: Listing,
    event_type: str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    transition_at: datetime | None = None,
) -> str:
    payload = {
        "source": listing.source,
        "source_listing_id": listing.source_listing_id,
        "episode_key": listing.episode_key,
        "event_type": event_type,
        "old_value": old_value,
        "new_value": new_value,
        "transition_at": transition_at.isoformat() if transition_at else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _record(
    session: Session,
    *,
    property_record: Property,
    listing: Listing,
    event_type: str,
    occurred_at: datetime,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    transition_at: datetime | None = None,
) -> bool:
    fingerprint = _fingerprint(
        listing, event_type, old_value, new_value, transition_at=transition_at
    )
    if session.scalar(
        select(PropertyEvent.id).where(PropertyEvent.event_fingerprint == fingerprint)
    ):
        return False
    session.add(
        PropertyEvent(
            property_id=property_record.id,
            listing_id=listing.id,
            event_fingerprint=fingerprint,
            event_type=event_type,
            source=listing.source,
            occurred_at=occurred_at,
            old_value=old_value,
            new_value=new_value,
        )
    )
    return True


def _status_group(status: str | None) -> str:
    normalized = (status or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if "sold" in normalized:
        return "sold"
    if normalized in {"active", "for_sale", "coming_soon", "pending", "contingent"}:
        return "market"
    if normalized in {"unavailable", "off_market", "delisted", "out_of_stock"}:
        return "off_market"
    return "unknown"


def derive_listing_events(
    session: Session,
    *,
    property_record: Property,
    listing: Listing,
    current_state: ListingState,
    previous_state: ListingState | None,
    listing_created: bool,
    observed_at: datetime,
) -> int:
    occurred_at = current_state.source_updated_at or observed_at
    created = 0
    if listing_created or previous_state is None:
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="first_seen",
            occurred_at=listing.first_seen_at,
            old_value=None,
            new_value={
                "price": _json_value(current_state.price),
                "status": current_state.status,
                "url": listing.url,
            },
        )
        if _status_group(current_state.status) == "sold":
            created += _record(
                session,
                property_record=property_record,
                listing=listing,
                event_type="sold",
                occurred_at=occurred_at,
                old_value=None,
                new_value={
                    "status": current_state.status,
                    "price": _json_value(current_state.price),
                },
            )
        return created

    if previous_state.id == current_state.id:
        return created
    transition_at = observed_at
    if (
        previous_state.price is not None
        and current_state.price is not None
        and previous_state.price != current_state.price
    ):
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="price_change",
            occurred_at=occurred_at,
            old_value={"price": str(previous_state.price)},
            new_value={"price": str(current_state.price)},
            transition_at=transition_at,
        )

    old_status = previous_state.status
    new_status = current_state.status
    old_group = _status_group(old_status)
    new_group = _status_group(new_status)
    if old_status != new_status and new_status is not None:
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="status_change",
            occurred_at=occurred_at,
            old_value={"status": old_status},
            new_value={"status": new_status},
            transition_at=transition_at,
        )
    if old_group == "market" and new_group == "off_market":
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="delisted",
            occurred_at=occurred_at,
            old_value={"status": old_status},
            new_value={"status": new_status},
            transition_at=transition_at,
        )
    elif old_group == "off_market" and new_group == "market":
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="relisted",
            occurred_at=occurred_at,
            old_value={"status": old_status},
            new_value={"status": new_status},
            transition_at=transition_at,
        )
    if new_group == "sold" and old_group != "sold":
        created += _record(
            session,
            property_record=property_record,
            listing=listing,
            event_type="sold",
            occurred_at=occurred_at,
            old_value={"status": old_status},
            new_value={"status": new_status, "price": _json_value(current_state.price)},
            transition_at=transition_at,
        )
    return created


def property_history(session: Session, property_id: int) -> PropertyHistoryResponse | None:
    if session.get(Property, property_id) is None:
        return None
    rows = session.execute(
        select(PropertyEvent, Listing.url)
        .outerjoin(Listing, Listing.id == PropertyEvent.listing_id)
        .where(PropertyEvent.property_id == property_id)
        .order_by(PropertyEvent.occurred_at.desc(), PropertyEvent.id.desc())
    ).all()
    return PropertyHistoryResponse(
        property_id=property_id,
        events=[
            PropertyEventView(
                id=event.id,
                event_type=event.event_type,
                source=event.source,
                source_url=url,
                occurred_at=event.occurred_at,
                old_value=event.old_value,
                new_value=event.new_value,
            )
            for event, url in rows
        ],
    )


def backfill_property_events(session: Session) -> int:
    created = 0
    listings = session.scalars(
        select(Listing).options(
            joinedload(Listing.property),
            selectinload(Listing.states),
        )
    ).all()
    for listing in listings:
        observations = session.scalars(
            select(ScanObservation)
            .where(ScanObservation.listing_id == listing.id)
            .order_by(ScanObservation.observed_at, ScanObservation.id)
        ).all()
        sequence: list[tuple[ListingState, datetime]] = []
        for observation in observations:
            if sequence and sequence[-1][0].id == observation.listing_state_id:
                continue
            state = next(
                (item for item in listing.states if item.id == observation.listing_state_id),
                None,
            )
            if state is not None:
                sequence.append((state, observation.observed_at))
        if not sequence:
            sequence = [
                (state, state.created_at)
                for state in sorted(listing.states, key=lambda item: (item.created_at, item.id))
            ]
        previous: ListingState | None = None
        for index, (state, observed_at) in enumerate(sequence):
            created += derive_listing_events(
                session,
                property_record=listing.property,
                listing=listing,
                current_state=state,
                previous_state=previous,
                listing_created=index == 0,
                observed_at=observed_at,
            )
            previous = state
    return created
