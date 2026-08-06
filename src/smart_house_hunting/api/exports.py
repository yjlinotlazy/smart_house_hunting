from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from smart_house_hunting.db.models import Listing, ListingState, Property, PropertyEvent

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _csv_response(name: str, header: list[str], rows: list[list[object]]) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/properties.csv")
async def export_properties(request: Request) -> Response:
    with request.app.state.session_factory() as session:
        records = session.execute(
            select(Property, Listing, ListingState)
            .join(Listing, Listing.property_id == Property.id)
            .join(ListingState, ListingState.listing_id == Listing.id)
            .order_by(Property.id, Listing.source, ListingState.id.desc())
        ).all()
    seen: set[tuple[int, str]] = set()
    rows = []
    for prop, listing, state in records:
        key = (prop.id, listing.source)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            [
                prop.id,
                prop.street_address,
                prop.unit_number or "",
                prop.municipality,
                prop.state,
                prop.postal_code or "",
                listing.source,
                listing.url,
                state.status or "",
                state.price or "",
                state.bedrooms or "",
                state.bathrooms or "",
                state.living_area_sqft or "",
                state.lot_size_sqft or "",
                state.facts.get("year_built", ""),
                state.created_at.isoformat(),
            ]
        )
    return _csv_response(
        "properties.csv",
        [
            "property_id",
            "street_address",
            "unit",
            "municipality",
            "state",
            "postal_code",
            "source",
            "source_url",
            "status",
            "price",
            "bedrooms",
            "bathrooms",
            "living_area_sqft",
            "lot_size_sqft",
            "year_built",
            "state_created_at",
        ],
        rows,
    )


@router.get("/history.csv")
async def export_history(request: Request) -> Response:
    with request.app.state.session_factory() as session:
        records = session.execute(
            select(PropertyEvent, Property)
            .join(Property, Property.id == PropertyEvent.property_id)
            .order_by(PropertyEvent.occurred_at)
        ).all()
    rows = [
        [
            event.property_id,
            prop.street_address,
            prop.municipality,
            event.event_type,
            event.source or "",
            event.source_url or "",
            event.occurred_at.isoformat(),
            event.old_value or "",
            event.new_value or "",
        ]
        for event, prop in records
    ]
    return _csv_response(
        "history.csv",
        [
            "property_id",
            "street_address",
            "municipality",
            "event_type",
            "source",
            "source_url",
            "occurred_at",
            "old_value",
            "new_value",
        ],
        rows,
    )
