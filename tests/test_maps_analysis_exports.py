from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.db.models import Listing, ListingState, Property
from smart_house_hunting.llm.provider import FakeLLMProvider
from smart_house_hunting.main import create_app
from smart_house_hunting.maps.google import NearbyPlace
from smart_house_hunting.sources import FixtureSourceAdapter


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def create_config(tmp_path: Path, *, maps: bool = False) -> Path:
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    config["profile_file"] = str(tmp_path / "profile.yaml")
    config["search"]["municipalities"] = ["Example Town"]
    config["maps"]["enabled"] = maps
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


class FakeMaps:
    def __init__(self) -> None:
        self.nearby_calls = 0
        self.route_calls = 0

    async def nearby(self, *_args) -> list[NearbyPlace]:
        self.nearby_calls += 1
        return [
            NearbyPlace(
                place_id="place-one",
                name="Example Park",
                primary_type="park",
                types=["park"],
                address="Public place",
                latitude=42.1,
                longitude=-71.1,
                maps_uri="https://maps.google.com/",
            )
        ]

    async def walking(self, *_args) -> tuple[int, int]:
        self.route_calls += 1
        return 800, 600

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_maps_confirmation_cache_and_key_separation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake-demo-value")
    fake = FakeMaps()
    app = create_app(
        config_path=create_config(tmp_path, maps=True),
        database_path=tmp_path / "app.db",
        maps_client_factory=lambda _key: fake,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        with app.state.session_factory.begin() as session:
            prop = Property(
                street_address="1 Example Street",
                municipality="Example Town",
                state="MA",
                latitude=42,
                longitude=-71,
            )
            session.add(prop)
            session.flush()
            property_id = prop.id
        browser = await client.get("/api/maps/browser-config")
        refused = await client.post(
            "/api/maps/nearby-analyses",
            json={"property_ids": [property_id], "categories": ["parks"]},
        )
        first = await client.post(
            "/api/maps/nearby-analyses",
            json={
                "property_ids": [property_id],
                "categories": ["parks"],
                "confirm_google": True,
            },
        )
        cached = await client.post(
            "/api/maps/nearby-analyses",
            json={"property_ids": [property_id], "categories": ["parks"]},
        )

    assert browser.json() == {
        "enabled": True,
        "available": True,
        "api_key": "fake-demo-value",
    }
    assert "backend_api_key" not in browser.text
    assert refused.status_code == 409
    assert first.json()["results"][0]["walking_duration_seconds"] == 600
    assert cached.json()["counters"]["cached"] == 1
    assert fake.nearby_calls == fake.route_calls == 1


@pytest.mark.anyio
async def test_llm_explicit_action_cache_and_csv_exports(tmp_path: Path) -> None:
    fake = FakeLLMProvider(
        [
            {
                "must_have": [{"id": "m1", "description": "Enough bedrooms"}],
                "good_to_have": [],
            },
            {
                "must_have": [{"id": "m1", "result": "unknown", "evidence": "No bedroom fact"}],
                "good_to_have": [],
                "summary": "More information is needed.",
                "missing_information": ["bedrooms"],
            },
            {
                "overview": "One property was compared; more bedroom evidence is needed.",
                "top_choices": [
                    {
                        "property_id": 1,
                        "address": "1 Example Street",
                        "reason": "It is the only current candidate.",
                        "strengths": [],
                        "concerns": ["Bedroom count is unknown."],
                    }
                ],
                "disqualifiers": [],
                "tradeoffs": [],
                "financial_comparison": "Only one property is available for comparison.",
                "shared_unknowns": ["Bedroom count"],
            },
        ]
    )
    app = create_app(
        config_path=create_config(tmp_path),
        database_path=tmp_path / "app.db",
        llm_provider_factory=lambda _name, _config: fake,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        with app.state.session_factory.begin() as session:
            prop = Property(
                street_address="1 Example Street", municipality="Example Town", state="MA"
            )
            session.add(prop)
            session.flush()
            property_id = prop.id
            listing = Listing(
                property_id=property_id,
                source="redfin",
                source_listing_id="example-1",
                url="https://example.invalid/listing/1",
                first_seen_at=datetime(2026, 8, 5, tzinfo=UTC),
                last_seen_at=datetime(2026, 8, 5, tzinfo=UTC),
            )
            session.add(listing)
            session.flush()
            session.add(
                ListingState(
                    listing_id=listing.id,
                    content_hash="a" * 64,
                    status="active",
                    description="Sunny home with an attached garage.",
                    facts={
                        "property_type": "single_family",
                        "amenities": ["Attached garage"],
                        "image_urls": ["https://images.example.invalid/1.jpg"],
                    },
                )
            )
        first = await client.post(
            "/api/analyses",
            json={"property_ids": [property_id]},
        )
        second = await client.post(
            "/api/analyses",
            json={"property_ids": [property_id]},
        )
        latest = await client.get("/api/analyses/latest")
        properties_csv = await client.get("/api/exports/properties.csv")
        history_csv = await client.get("/api/exports/history.csv")

    assert first.json()["status"] == "success"
    assert second.json()["counters"]["cached"] == 1
    assert second.json()["counters"]["digest_cached"] == 1
    assert len(fake.calls) == 3
    criteria_system, criteria_user = fake.calls[0]
    evaluation_system, evaluation_user = fake.calls[1]
    digest_system, digest_user = fake.calls[2]
    assert "criteria-v2" in criteria_system
    assert "untrusted data" in criteria_system
    assert "stable, descriptive snake_case ID" in criteria_system
    assert "output_schema" in json.loads(criteria_user)
    assert "property-v3" in evaluation_system
    assert "never a failure" in evaluation_system
    assert "0 = directly contrary" in evaluation_system
    evaluation_payload = json.loads(evaluation_user)
    assert "output_schema" in evaluation_payload
    listing_content = evaluation_payload["property"]["listing_content"][0]
    assert listing_content["url"] == "https://example.invalid/listing/1"
    assert listing_content["description"] == "Sunny home with an attached garage."
    assert listing_content["facts"]["amenities"] == ["Attached garage"]
    assert "image_urls" not in listing_content["facts"]
    assert "digest-v1" in digest_system
    assert "Unknown is never a" in digest_system
    assert "output_schema" in json.loads(digest_user)
    assert latest.json()["results"][0]["result"]["must_have"][0]["result"] == "unknown"
    assert latest.json()["digest"]["result"]["top_choices"][0]["property_id"] == property_id
    assert latest.json()["digest"]["freshness"] == "fresh"
    assert properties_csv.status_code == history_csv.status_code == 200
    assert properties_csv.text.startswith("property_id,street_address")


@pytest.mark.anyio
async def test_local_workflow_profile_scan_maps_analysis_and_export(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake-demo-value")
    config_path = create_config(tmp_path, maps=True)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["search"]["municipalities"] = ["Belmont"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    maps = FakeMaps()
    llm = FakeLLMProvider(
        [
            {"must_have": [], "good_to_have": [], "ambiguities": []},
            {
                "must_have": [],
                "good_to_have": [],
                "summary": "No configured criteria.",
                "missing_information": [],
            },
            {
                "overview": "One fixture property was analyzed.",
                "top_choices": [],
                "disqualifiers": [],
                "tradeoffs": [],
                "financial_comparison": "Only one property is available.",
                "shared_unknowns": [],
            },
        ]
    )
    app = create_app(
        config_path=config_path,
        database_path=tmp_path / "app.db",
        source_adapters=[FixtureSourceAdapter("redfin")],
        maps_client_factory=lambda _key: maps,
        llm_provider_factory=lambda _name, _config: llm,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        saved = await client.put(
            "/api/profile",
            json={
                "family": "Local test household",
                "must_have": "",
                "good_to_have": "",
                "finance": {
                    "current_annual_gross_income": "0",
                    "minimum_future_annual_gross_income": "0",
                    "annual_travel_spending": "0",
                    "down_payment": {"mode": "amount", "value": "0"},
                },
            },
        )
        started = await client.post("/api/scans", json={})
        job_id = started.json()["job"]["id"]
        for _ in range(100):
            job = (await client.get(f"/api/scans/{job_id}")).json()
            if job["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)
        properties = (await client.get("/api/properties")).json()["properties"]
        property_id = properties[0]["id"]
        nearby = await client.post(
            "/api/maps/nearby-analyses",
            json={
                "property_ids": [property_id],
                "categories": ["parks"],
                "confirm_google": True,
            },
        )
        analyzed = await client.post(
            "/api/analyses",
            json={"property_ids": [property_id]},
        )
        exported = await client.get("/api/exports/properties.csv")

    assert saved.status_code == 200
    assert job["status"] == "success"
    assert nearby.json()["status"] == "success"
    assert analyzed.json()["status"] == "success"
    assert str(property_id) in exported.text
