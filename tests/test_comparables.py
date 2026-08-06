from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from smart_house_hunting.db.engine import create_session_factory, create_sqlite_engine
from smart_house_hunting.db.migration import initialize_database
from smart_house_hunting.db.models import Property, ScanJob
from smart_house_hunting.services.comparables import (
    property_comparables,
    refresh_sold_comparables,
)
from smart_house_hunting.services.ingest import ingest_candidate
from smart_house_hunting.sources import NormalizedListing


def candidate(
    listing_id: str,
    address: str,
    *,
    municipality: str = "Belmont",
    sale: bool = False,
) -> NormalizedListing:
    number = int(listing_id.rsplit("-", 1)[-1])
    facts: dict[str, object] = {
        "property_type": "single_family",
        "year_built": 1940,
    }
    if sale:
        facts["sold_history"] = [
            {
                "sale_date": "2025-06-01",
                "sale_price": "810000",
                "original_listing_price": "850000",
                "final_listing_price": "820000",
            }
        ]
    return NormalizedListing(
        source="realtor",
        source_listing_id=listing_id,
        url=f"https://example.invalid/{listing_id}",
        street_address=address,
        municipality=municipality,
        latitude=Decimal("42.30") + Decimal(number) / Decimal("1000"),
        longitude=Decimal("-71.20"),
        price=Decimal("900000"),
        status="active",
        bedrooms=Decimal("3"),
        bathrooms=Decimal("2"),
        living_area_sqft=1800,
        lot_size_sqft=Decimal("10000"),
        facts=facts,
    )


def test_same_town_comparables_and_price_differences(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    engine = create_sqlite_engine(path)
    initialize_database(engine, path)
    sessions = create_session_factory(engine)
    observed = datetime(2026, 8, 5, 12, tzinfo=UTC)
    listings = [candidate("listing-0", "10 Candidate Rd")]
    listings.extend(
        candidate(f"listing-{index}", f"{10 + index} Sold Rd", sale=True) for index in range(1, 4)
    )
    listings.append(candidate("listing-4", "20 Nearby Rd", municipality="Newton", sale=True))

    with sessions.begin() as session:
        scan = ScanJob(status="running", config_fingerprint="a" * 64)
        session.add(scan)
        session.flush()
        for item in listings:
            ingest_candidate(
                session,
                scan_job=scan,
                candidate=item,
                configured_municipalities=["Belmont", "Newton"],
                observed_at=observed,
            )
        refresh_sold_comparables(session, municipalities=["Belmont"], retrieved_at=observed)

    with sessions() as session:
        property_id = session.scalar(
            select(Property.id).where(Property.street_address == "10 Candidate Rd")
        )
        assert property_id is not None
        response = property_comparables(session, property_id)

    assert response is not None
    assert len(response.comparables) == 3
    assert not response.expanded_to_nearby_towns
    assert all(item.scope == "same_town" for item in response.comparables)
    assert response.comparables[0].difference_from_original == Decimal("-40000")
    assert response.comparables[0].difference_from_final == Decimal("-10000")
    assert "same municipality" in response.comparables[0].similarity_reasons
    engine.dispose()
