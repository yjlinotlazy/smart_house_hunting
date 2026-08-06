from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from smart_house_hunting.db.models import Listing, ListingState, Property, SoldComparable
from smart_house_hunting.properties.models import SoldComparableResponse, SoldComparableView

SOURCE_PRIORITY = {"redfin": 0, "zillow": 1, "realtor": 2}


@dataclass(frozen=True)
class SoldRecord:
    property_record: Property
    listing: Listing
    state: ListingState
    source_record_id: str
    sale_date: date | None
    sale_price: Decimal | None
    original_listing_price: Decimal | None
    final_listing_price: Decimal | None


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _latest(listing: Listing) -> ListingState | None:
    return max(listing.states, key=lambda state: (state.created_at, state.id), default=None)


def _property_states(property_record: Property) -> list[tuple[Listing, ListingState]]:
    values = [
        (listing, state)
        for listing in property_record.listings
        if (state := _latest(listing)) is not None
    ]
    return sorted(values, key=lambda item: SOURCE_PRIORITY.get(item[0].source, 99))


def _display_state(property_record: Property) -> ListingState | None:
    states = _property_states(property_record)
    return states[0][1] if states else None


def _market_candidate(property_record: Property) -> bool:
    statuses = {(state.status or "").casefold() for _, state in _property_states(property_record)}
    return bool(statuses & {"active", "for_sale", "coming_soon", "pending", "contingent"})


def _sold_records(properties: list[Property]) -> list[SoldRecord]:
    records: list[SoldRecord] = []
    seen: set[tuple[int, date | None, Decimal | None]] = set()
    for property_record in properties:
        for listing, state in _property_states(property_record):
            history = state.facts.get("sold_history")
            if not isinstance(history, list):
                continue
            for index, item in enumerate(history):
                if not isinstance(item, dict):
                    continue
                sale_date = _date(item.get("sale_date"))
                sale_price = _decimal(item.get("sale_price"))
                if sale_date is None and sale_price is None:
                    continue
                source_record_id = (
                    f"{listing.source_listing_id}:"
                    f"{sale_date.isoformat() if sale_date else 'unknown'}:"
                    f"{sale_price if sale_price is not None else 'unknown'}:{index}"
                )
                key = (property_record.id, sale_date, sale_price)
                if key in seen:
                    continue
                seen.add(key)
                records.append(
                    SoldRecord(
                        property_record=property_record,
                        listing=listing,
                        state=state,
                        source_record_id=source_record_id,
                        sale_date=sale_date,
                        sale_price=sale_price,
                        original_listing_price=_decimal(item.get("original_listing_price")),
                        final_listing_price=_decimal(item.get("final_listing_price")),
                    )
                )
    return records


def _distance_miles(first: Property, second: Property) -> Decimal | None:
    if None in (first.latitude, first.longitude, second.latitude, second.longitude):
        return None
    lat1 = math.radians(float(first.latitude))
    lat2 = math.radians(float(second.latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(second.longitude - first.longitude))
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    miles = 3958.7613 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
    return Decimal(str(round(miles, 3)))


def _similarity(
    candidate: Property,
    candidate_state: ListingState,
    sold: SoldRecord,
    retrieved_at: datetime,
) -> tuple[int, list[str], Decimal | None]:
    score = 0
    reasons: list[str] = []
    same_town = candidate.municipality.casefold() == sold.property_record.municipality.casefold()
    if same_town:
        score += 40
        reasons.append("same municipality")
    candidate_type = candidate_state.facts.get("property_type")
    sold_type = sold.state.facts.get("property_type")
    if candidate_type and candidate_type == sold_type:
        score += 20
        reasons.append("same property type")
    if candidate_state.living_area_sqft and sold.state.living_area_sqft:
        difference = abs(candidate_state.living_area_sqft - sold.state.living_area_sqft)
        ratio = difference / candidate_state.living_area_sqft
        if ratio <= 0.10:
            score += 20
            reasons.append("living area within 10%")
        elif ratio <= 0.25:
            score += 10
            reasons.append("living area within 25%")
    if candidate_state.bedrooms is not None and sold.state.bedrooms is not None:
        difference = abs(candidate_state.bedrooms - sold.state.bedrooms)
        if difference == 0:
            score += 10
            reasons.append("same bedroom count")
        elif difference <= 1:
            score += 5
            reasons.append("bedroom count within one")
    if candidate_state.price is not None and sold.sale_price is not None:
        ratio = abs(candidate_state.price - sold.sale_price) / candidate_state.price
        if ratio <= Decimal("0.15"):
            score += 10
            reasons.append("sale price within 15% of list price")
        elif ratio <= Decimal("0.30"):
            score += 5
            reasons.append("sale price within 30% of list price")
    if sold.sale_date is not None:
        age_days = (retrieved_at.date() - sold.sale_date).days
        if 0 <= age_days <= 730:
            score += 10
            reasons.append("sold within two years")
        elif 0 <= age_days <= 1825:
            score += 5
            reasons.append("sold within five years")
    distance = _distance_miles(candidate, sold.property_record)
    if distance is not None:
        if distance <= 1:
            score += 10
            reasons.append("within one mile")
        elif distance <= 3:
            score += 5
            reasons.append("within three miles")
    return score, reasons, distance


def refresh_sold_comparables(
    session: Session,
    *,
    municipalities: list[str],
    retrieved_at: datetime,
    minimum_same_town: int = 3,
    maximum_results: int = 8,
) -> int:
    properties = list(
        session.scalars(
            select(Property).options(selectinload(Property.listings).selectinload(Listing.states))
        ).all()
    )
    sold_records = _sold_records(properties)
    configured = {name.casefold() for name in municipalities}
    created = 0
    for candidate in properties:
        if candidate.municipality.casefold() not in configured or not _market_candidate(candidate):
            continue
        candidate_state = _display_state(candidate)
        if candidate_state is None:
            continue
        ranked: list[tuple[bool, int, SoldRecord, list[str], Decimal | None]] = []
        for sold in sold_records:
            if sold.property_record.id == candidate.id:
                continue
            score, reasons, distance = _similarity(candidate, candidate_state, sold, retrieved_at)
            same_town = (
                candidate.municipality.casefold() == sold.property_record.municipality.casefold()
            )
            ranked.append((same_town, score, sold, reasons, distance))
        same_town = sorted(
            (item for item in ranked if item[0]), key=lambda item: item[1], reverse=True
        )
        selected = same_town[:maximum_results]
        expanded = len(selected) < minimum_same_town
        if expanded:
            nearby = sorted(
                (item for item in ranked if not item[0]),
                key=lambda item: (
                    item[4] is None,
                    item[4] if item[4] is not None else Decimal("Infinity"),
                    -item[1],
                ),
            )
            selected.extend(nearby[: maximum_results - len(selected)])

        session.execute(
            delete(SoldComparable).where(SoldComparable.candidate_property_id == candidate.id)
        )
        for is_same_town, score, sold, reasons, distance in selected:
            session.add(
                SoldComparable(
                    candidate_property_id=candidate.id,
                    sold_property_id=sold.property_record.id,
                    source=sold.listing.source,
                    source_record_id=sold.source_record_id,
                    url=sold.listing.url,
                    sale_date=sold.sale_date,
                    sale_price=sold.sale_price,
                    original_listing_price=sold.original_listing_price,
                    final_listing_price=sold.final_listing_price,
                    distance_miles=distance,
                    similarity={
                        "score": score,
                        "reasons": reasons,
                        "scope": "same_town" if is_same_town else "nearby_town_expansion",
                        "expanded": expanded and not is_same_town,
                        "sold_snapshot": {
                            "street_address": sold.property_record.street_address,
                            "municipality": sold.property_record.municipality,
                            "property_type": sold.state.facts.get("property_type"),
                            "bedrooms": str(sold.state.bedrooms)
                            if sold.state.bedrooms is not None
                            else None,
                            "bathrooms": str(sold.state.bathrooms)
                            if sold.state.bathrooms is not None
                            else None,
                            "living_area_sqft": sold.state.living_area_sqft,
                        },
                    },
                    retrieved_at=retrieved_at,
                )
            )
            created += 1
    return created


def property_comparables(session: Session, property_id: int) -> SoldComparableResponse | None:
    if session.get(Property, property_id) is None:
        return None
    rows = list(
        session.scalars(
            select(SoldComparable).where(SoldComparable.candidate_property_id == property_id)
        ).all()
    )
    rows.sort(
        key=lambda row: int(row.similarity.get("score", 0)),
        reverse=True,
    )
    views: list[SoldComparableView] = []
    for row in rows:
        snapshot = row.similarity.get("sold_snapshot", {})
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        missing = [
            name
            for name, value in {
                "sale_date": row.sale_date,
                "sale_price": row.sale_price,
                "original_listing_price": row.original_listing_price,
                "final_listing_price": row.final_listing_price,
                "bedrooms": snapshot.get("bedrooms"),
                "bathrooms": snapshot.get("bathrooms"),
                "living_area_sqft": snapshot.get("living_area_sqft"),
            }.items()
            if value is None
        ]
        reasons = row.similarity.get("reasons", [])
        views.append(
            SoldComparableView(
                id=row.id,
                source=row.source,
                url=row.url,
                street_address=str(snapshot["street_address"])
                if snapshot.get("street_address")
                else None,
                municipality=str(snapshot["municipality"])
                if snapshot.get("municipality")
                else None,
                sale_date=row.sale_date,
                sale_price=row.sale_price,
                original_listing_price=row.original_listing_price,
                final_listing_price=row.final_listing_price,
                difference_from_original=(
                    row.sale_price - row.original_listing_price
                    if row.sale_price is not None and row.original_listing_price is not None
                    else None
                ),
                difference_from_final=(
                    row.sale_price - row.final_listing_price
                    if row.sale_price is not None and row.final_listing_price is not None
                    else None
                ),
                property_type=str(snapshot["property_type"])
                if snapshot.get("property_type")
                else None,
                bedrooms=_decimal(snapshot.get("bedrooms")),
                bathrooms=_decimal(snapshot.get("bathrooms")),
                living_area_sqft=int(snapshot["living_area_sqft"])
                if snapshot.get("living_area_sqft") is not None
                else None,
                distance_miles=row.distance_miles,
                similarity_score=int(row.similarity.get("score", 0)),
                similarity_reasons=[str(reason) for reason in reasons]
                if isinstance(reasons, list)
                else [],
                scope=str(row.similarity.get("scope", "same_town")),
                retrieved_at=row.retrieved_at,
                missing_fields=missing,
            )
        )
    return SoldComparableResponse(
        property_id=property_id,
        comparables=views,
        expanded_to_nearby_towns=any(view.scope == "nearby_town_expansion" for view in views),
    )
