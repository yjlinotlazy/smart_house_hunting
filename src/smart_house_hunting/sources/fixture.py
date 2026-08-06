from __future__ import annotations

import asyncio
from decimal import Decimal

from smart_house_hunting.sources.base import (
    CandidateCallback,
    NormalizedListing,
    ProgressCallback,
    ScanRequest,
)


class FixtureSourceAdapter:
    """Deterministic offline adapter used until live source milestones land."""

    parser_version = "fixture-v1"

    def __init__(self, source: str = "redfin") -> None:
        self.fixture_source = source
        self.name = f"fixture-{source}"

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]:
        results: list[NormalizedListing] = []
        total = len(request.municipalities)
        for index, municipality in enumerate(request.municipalities, start=1):
            await progress(
                "municipality_started",
                {"municipality": municipality, "current": index, "total": total},
            )
            await asyncio.sleep(0.05)
            slug = "-".join(municipality.casefold().split())
            municipality_input = {
                "redfin": municipality.upper(),
                "zillow": municipality.lower(),
                "realtor": municipality,
            }[self.fixture_source]
            street_one = {
                "redfin": "1 Fixture Lane",
                "zillow": "1 Fixture Ln.",
                "realtor": "1 FIXTURE LANE",
            }[self.fixture_source]
            price_one = {
                "redfin": Decimal("800000"),
                "zillow": Decimal("805000"),
                "realtor": Decimal("805000"),
            }[self.fixture_source]
            unit = "2" if self.fixture_source == "realtor" else "1"
            unit_price = Decimal("950000") if unit == "1" else Decimal("975000")
            town_results = [
                NormalizedListing(
                    source=self.name,
                    source_listing_id=f"{slug}-{self.fixture_source}-1",
                    url=f"https://example.invalid/{self.fixture_source}/{slug}/1",
                    street_address=street_one,
                    municipality=municipality_input,
                    postal_code="00000",
                    latitude=Decimal("42.3000000") + Decimal(index) / Decimal(1000),
                    longitude=Decimal("-71.2000000") - Decimal(index) / Decimal(1000),
                    parcel_id=f"fixture-{slug}-001",
                    price=price_one,
                    status="active",
                    bedrooms=Decimal("3"),
                    bathrooms=Decimal("2"),
                    living_area_sqft=1800,
                    property_tax_annual=Decimal("9000"),
                    facts={"property_type": "single_family"},
                ),
                NormalizedListing(
                    source=self.name,
                    source_listing_id=f"{slug}-{self.fixture_source}-2-unit-{unit}",
                    url=f"https://example.invalid/{self.fixture_source}/{slug}/2-{unit}",
                    street_address="2 Fixture Lane",
                    unit_number=unit,
                    municipality=municipality_input,
                    postal_code="00000",
                    latitude=Decimal("42.3010000") + Decimal(index) / Decimal(1000),
                    longitude=Decimal("-71.2010000") - Decimal(index) / Decimal(1000),
                    parcel_id=f"fixture-{slug}-002-{unit}",
                    price=unit_price,
                    status="active",
                    bedrooms=Decimal("2"),
                    bathrooms=Decimal("2"),
                    living_area_sqft=1200,
                    property_tax_annual=Decimal("7000"),
                    hoa_monthly=Decimal("450"),
                    facts={"property_type": "condo"},
                ),
            ]
            selected = [
                listing
                for listing in town_results
                if listing.facts.get("property_type") in request.included_property_types
                and listing.bedrooms is not None
                and listing.bedrooms >= request.minimum_bedrooms
                and listing.bathrooms is not None
                and listing.bathrooms >= request.minimum_bathrooms
            ]
            for listing in selected:
                results.append(listing)
                if on_candidate is not None:
                    await on_candidate(listing)
            await progress(
                "municipality_completed",
                {"municipality": municipality, "current": index, "total": total},
            )
        return results
