from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from smart_house_hunting.db.engine import create_session_factory, create_sqlite_engine
from smart_house_hunting.db.migration import initialize_database
from smart_house_hunting.db.models import (
    Listing,
    ListingState,
    Property,
    PropertyDuplicateCandidate,
    ScanJob,
    ScanObservation,
)
from smart_house_hunting.main import create_app
from smart_house_hunting.normalization import normalize_address, normalize_municipality
from smart_house_hunting.services.ingest import ingest_candidate
from smart_house_hunting.sources import FixtureSourceAdapter, NormalizedListing


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def create_config(tmp_path: Path) -> Path:
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    config["profile_file"] = str(tmp_path / "profile.yaml")
    config["search"]["municipalities"] = ["Belmont", "Newton"]
    config["search"]["included_property_types"] = ["single_family", "condo"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


async def wait_for_scan(client: AsyncClient, job_id: int) -> None:
    for _ in range(100):
        job = (await client.get(f"/api/scans/{job_id}")).json()
        if job["status"] not in {"queued", "running"}:
            assert job["status"] == "success"
            return
        await asyncio.sleep(0.01)
    raise AssertionError("scan did not finish")


def test_massachusetts_address_and_unit_normalization() -> None:
    assert normalize_municipality(" town of BELMONT ", ["Belmont", "Newton"]) == "Belmont"
    address = normalize_address("10 North Main Street, Apt 01")
    assert address.street_key == "10 N MAIN ST"
    assert address.unit == "1"

    with pytest.raises(ValueError, match="outside"):
        normalize_municipality("Cambridge", ["Belmont", "Newton"])


@pytest.mark.anyio
async def test_fixture_results_deduplicate_preserve_units_provenance_and_finance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.db"
    app = create_app(
        config_path=create_config(tmp_path),
        database_path=database_path,
        source_adapters=[
            FixtureSourceAdapter("redfin"),
            FixtureSourceAdapter("zillow"),
            FixtureSourceAdapter("realtor"),
        ],
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        started = await client.post("/api/scans", json={})
        await wait_for_scan(client, started.json()["job"]["id"])
        results = await client.get("/api/properties?sort=town")
        filtered = await client.get(
            "/api/properties", params={"municipality": "Belmont", "max_price": "900000"}
        )
        await client.post("/api/scans", json={})
        await wait_for_scan(client, 2)

        properties = results.json()["properties"]
        belmont = [item for item in properties if item["municipality"] == "Belmont"]
        detached = next(item for item in belmont if item["street_address"] == "1 Fixture Ln")
        manual = await client.patch(
            f"/api/properties/{detached['id']}/manual-facts",
            json={
                "lot_size_sqft": "12345",
                "hoa_monthly": "0",
                "year_built": 1950,
                "image_url": "https://images.example.invalid/manual.jpg",
            },
        )
        tagged = await client.put(
            f"/api/properties/{detached['id']}/manual-tags",
            json={"tags": ["Corner lot", "双黄线", "Corner lot", "  临街  噪音 "]},
        )
        invalid_tag = await client.put(
            f"/api/properties/{detached['id']}/manual-tags",
            json={"tags": [" "]},
        )
        with app.state.session_factory.begin() as session:
            listing = session.scalar(
                select(Listing).where(
                    Listing.property_id == detached["id"],
                    Listing.source == "fixture-redfin",
                )
            )
            latest = max(listing.states, key=lambda state: state.id)
            session.add(
                ListingState(
                    listing_id=listing.id,
                    content_hash="d" * 64,
                    status=latest.status,
                    price=latest.price,
                    bedrooms=latest.bedrooms,
                    bathrooms=latest.bathrooms,
                    living_area_sqft=latest.living_area_sqft,
                    lot_size_sqft=None,
                    property_tax_annual=latest.property_tax_annual,
                    hoa_monthly=latest.hoa_monthly,
                    description=latest.description,
                    facts=latest.facts,
                )
            )
        manual_after_missing_crawl = await client.get(f"/api/properties/{detached['id']}")
        with app.state.session_factory.begin() as session:
            listing = session.scalar(
                select(Listing).where(
                    Listing.property_id == detached["id"],
                    Listing.source == "fixture-redfin",
                )
            )
            latest = max(listing.states, key=lambda state: state.id)
            session.add(
                ListingState(
                    listing_id=listing.id,
                    content_hash="e" * 64,
                    status=latest.status,
                    price=latest.price,
                    bedrooms=latest.bedrooms,
                    bathrooms=latest.bathrooms,
                    living_area_sqft=latest.living_area_sqft,
                    lot_size_sqft=Decimal("22222"),
                    property_tax_annual=latest.property_tax_annual,
                    hoa_monthly=latest.hoa_monthly,
                    description=latest.description,
                    facts=latest.facts,
                )
            )
        detail = await client.get(f"/api/properties/{detached['id']}")
        history = await client.get(f"/api/properties/{detached['id']}/history")
        comparables = await client.get(f"/api/properties/{detached['id']}/comparables")
        units = sorted(
            item["unit_number"] for item in belmont if item["street_address"] == "2 Fixture Ln"
        )

        assert results.json()["count"] == 6
        assert len(belmont) == 3
        assert units == ["1", "2"]
        assert len(detached["sources"]) == 3
        assert detached["price"]["display_value"] == "800000.00"
        assert detached["retrieval_status"] == "partially_retrieved"
        assert {"lot_size_sqft", "year_built", "image_url"}.issubset(detached["missing_fields"])
        assert "hoa_monthly" not in detached["missing_fields"]
        assert manual.json()["lot_size_sqft"]["display_value"] == "12345"
        assert manual.json()["lot_size_sqft"]["source_values"][-1] == {
            "source": "manual",
            "value": "12345",
        }
        assert manual.json()["retrieval_status"] == "retrieved"
        assert manual_after_missing_crawl.json()["lot_size_sqft"]["display_value"] == "12345"
        assert detail.json()["lot_size_sqft"]["display_value"] == "22222.00"
        assert all(
            value["source"] != "manual" for value in detail.json()["lot_size_sqft"]["source_values"]
        )
        assert detail.json()["manual_values"]["lot_size_sqft"] == "12345"
        assert detached["manual_tags"] == []
        assert tagged.json()["manual_tags"] == ["Corner lot", "双黄线", "临街 噪音"]
        assert invalid_tag.status_code == 422
        assert detail.json()["manual_tags"] == ["Corner lot", "双黄线", "临街 噪音"]
        assert detached["price"]["conflict"] is True
        assert "price" in detached["conflict_fields"]
        assert detached["financials"]["down_payment"] == {
            "authoritative_mode": "percent",
            "amount": "160000.00",
            "percent": "20.00",
        }
        assert detached["financials"]["loan_amount"] == "640000.00"
        assert [source["url"] for source in detail.json()["sources"]] == [
            source["url"] for source in detached["sources"]
        ]
        assert {event["event_type"] for event in history.json()["events"]} == {"first_seen"}
        assert comparables.json()["comparables"] == []
        assert "not a price prediction" in comparables.json()["disclaimer"]
        assert filtered.json()["count"] == 1
        acres_update = await client.patch(
            f"/api/properties/{detached['id']}/manual-facts",
            json={"lot_size_sqft": None, "lot_size_acres": "0.29"},
        )
        assert acres_update.json()["manual_values"]["lot_size_sqft"] == "12632.40"

        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(Property.id))) == 6
            assert session.scalar(select(func.count(Listing.id))) == 12
            assert session.scalar(select(func.count(ListingState.id))) == 14
            assert session.scalar(select(func.count(ScanObservation.id))) == 24


def test_high_confidence_match_and_ambiguous_unit_remain_reversible(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    engine = create_sqlite_engine(path)
    initialize_database(engine, path)
    session_factory = create_session_factory(engine)
    observed_at = datetime(2026, 8, 5, 12, tzinfo=UTC)

    def candidate(
        source: str,
        address: str,
        unit: str | None,
        latitude: str | None,
        parcel_id: str | None = None,
    ) -> NormalizedListing:
        return NormalizedListing(
            source=source,
            source_listing_id=f"{source}-{address}-{unit}",
            url=f"https://example.invalid/{source}",
            street_address=address,
            unit_number=unit,
            municipality="Belmont",
            latitude=Decimal(latitude) if latitude else None,
            longitude=Decimal("-71.2000000") if latitude else None,
            parcel_id=parcel_id,
            price=Decimal("800000"),
            bedrooms=Decimal("3"),
            living_area_sqft=1800,
            facts={"property_type": "single_family"},
        )

    with session_factory.begin() as session:
        scan = ScanJob(status="running", config_fingerprint="a" * 64, counters={})
        session.add(scan)
        session.flush()
        ingest_candidate(
            session,
            scan_job=scan,
            candidate=candidate("one", "10 Example Road", None, "42.3000000"),
            configured_municipalities=["Belmont"],
            observed_at=observed_at,
        )
        ingest_candidate(
            session,
            scan_job=scan,
            candidate=candidate("two", "10 Example Avenue", None, "42.3000000"),
            configured_municipalities=["Belmont"],
            observed_at=observed_at,
        )
        ingest_candidate(
            session,
            scan_job=scan,
            candidate=candidate("three", "20 Condo Lane", "1", None, "shared-building"),
            configured_municipalities=["Belmont"],
            observed_at=observed_at,
        )
        ingest_candidate(
            session,
            scan_job=scan,
            candidate=candidate("four", "20 Condo Lane", None, None, "shared-building"),
            configured_municipalities=["Belmont"],
            observed_at=observed_at,
        )

    with session_factory() as session:
        assert session.scalar(select(func.count(Property.id))) == 3
        duplicate = session.scalar(select(PropertyDuplicateCandidate))
        assert duplicate is not None
        assert duplicate.status == "possible"
        assert "unit" in duplicate.reason
    engine.dispose()
