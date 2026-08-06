from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from smart_house_hunting.sources.base import (
    NormalizedListing,
    detail_completed_today,
    missing_required_fields,
)


def complete_listing() -> NormalizedListing:
    return NormalizedListing(
        source="test",
        source_listing_id="one",
        url="https://example.invalid/one",
        street_address="10 Example Rd",
        municipality="Belmont",
        price=Decimal("900000"),
        status="active",
        bedrooms=Decimal("3"),
        bathrooms=Decimal("2"),
        living_area_sqft=1800,
        lot_size_sqft=Decimal("10000"),
        facts={
            "year_built": 1940,
            "image_urls": ["https://images.example.invalid/one.jpg"],
        },
        last_observed_at=datetime.now(UTC),
    )


def test_complete_listing_can_be_reused_today() -> None:
    listing = complete_listing()

    assert missing_required_fields(listing) == ()
    assert detail_completed_today(listing)


@pytest.mark.parametrize(
    ("field", "update"),
    [
        ("bedrooms", {"bedrooms": None}),
        ("bathrooms", {"bathrooms": None}),
        ("price", {"price": None}),
        ("lot_size_sqft", {"lot_size_sqft": None}),
        ("living_area_sqft", {"living_area_sqft": None}),
        ("status", {"status": None}),
        ("year_built", {"facts": {"image_urls": ["https://example.invalid/one.jpg"]}}),
        ("image", {"facts": {"year_built": 1940, "image_urls": []}}),
    ],
)
def test_missing_required_field_prevents_reuse(field: str, update: dict[str, object]) -> None:
    listing = complete_listing().model_copy(update=update)

    assert field in missing_required_fields(listing)
    assert not detail_completed_today(listing)
