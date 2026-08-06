from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.main import create_app
from smart_house_hunting.sources.base import (
    CandidateCallback,
    NormalizedListing,
    ProgressCallback,
    ScanRequest,
)
from smart_house_hunting.sources.fixture import FixtureSourceAdapter


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def create_config(tmp_path: Path) -> Path:
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    config["profile_file"] = str(tmp_path / "profile.yaml")
    config["search"]["municipalities"] = ["Belmont", "Newton"]
    config["search"]["recent_scan_confirmation_minutes"] = 30
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def fixture_adapters() -> list[FixtureSourceAdapter]:
    return [
        FixtureSourceAdapter("redfin"),
        FixtureSourceAdapter("zillow"),
        FixtureSourceAdapter("realtor"),
    ]


async def wait_for_terminal(client: AsyncClient, job_id: int) -> dict:
    for _ in range(100):
        response = await client.get(f"/api/scans/{job_id}")
        job = response.json()
        if job["status"] not in {"queued", "running"}:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("scan did not finish")


@pytest.mark.anyio
async def test_go_flow_is_persisted_singleton_and_allows_user_controlled_repeats(
    tmp_path: Path,
) -> None:
    app = create_app(
        config_path=create_config(tmp_path),
        database_path=tmp_path / "app.db",
        source_adapters=fixture_adapters(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        first = await client.post("/api/scans", json={})
        duplicate = await client.post("/api/scans", json={})
        job_id = first.json()["job"]["id"]
        completed = await wait_for_terminal(client, job_id)
        status = await client.get("/api/scans/status")
        repeated = await client.post("/api/scans", json={})
        second_completed = await wait_for_terminal(client, repeated.json()["job"]["id"])
        forced = await client.post(
            "/api/scans",
            json={"force_refresh": True},
        )
        forced_completed = await wait_for_terminal(client, forced.json()["job"]["id"])
        changed_config = (await client.get("/api/settings")).json()
        changed_config["search"]["municipalities"].append("Cambridge")
        await client.put("/api/settings", json=changed_config)
        changed_towns = await client.post("/api/scans", json={})
        changed_completed = await wait_for_terminal(client, changed_towns.json()["job"]["id"])

    assert first.status_code == 202
    assert duplicate.json()["reused_active"] is True
    assert duplicate.json()["job"]["id"] == job_id
    assert completed["status"] == "success"
    assert completed["counters"]["candidates"] == 6
    assert completed["counters"]["properties"] == 2
    assert {run["source"] for run in completed["source_runs"]} == {
        "fixture-redfin",
        "fixture-zillow",
        "fixture-realtor",
    }
    assert status.json()["last_success"]["id"] == job_id
    assert repeated.status_code == 202
    assert second_completed["status"] == "success"
    assert forced.status_code == 202
    assert forced_completed["status"] == "success"
    assert changed_towns.status_code == 202
    assert changed_completed["counters"]["candidates"] == 9
    assert changed_completed["counters"]["properties"] == 3


class SuccessfulAdapter:
    name = "working-fixture"
    parser_version = "test-v1"

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]:
        await progress("working", {"towns": len(request.municipalities)})
        return []


class FailedAdapter:
    name = "failed-fixture"
    parser_version = "test-v1"

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]:
        raise RuntimeError("fixture failure")


class PartiallyFailedAdapter:
    name = "partial-fixture"
    parser_version = "test-v1"

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]:
        candidate = NormalizedListing(
            source=self.name,
            source_listing_id="partial-1",
            url="https://example.invalid/partial-1",
            street_address="99 Partial Rd",
            municipality="Belmont",
            price=900000,
            status="active",
            bedrooms=3,
            bathrooms=2,
            facts={"property_type": "single_family"},
        )
        if on_candidate is not None:
            await on_candidate(candidate)
        raise RuntimeError("failed after one candidate")


@pytest.mark.anyio
async def test_partial_source_failure_retains_success_and_events(tmp_path: Path) -> None:
    app = create_app(
        config_path=create_config(tmp_path),
        database_path=tmp_path / "app.db",
        source_adapters=[SuccessfulAdapter(), FailedAdapter()],
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        started = await client.post("/api/scans", json={})
        job_id = started.json()["job"]["id"]
        completed = await wait_for_terminal(client, job_id)
        events = await client.get(f"/api/scans/{job_id}/events")

    sources = {run["source"]: run["status"] for run in completed["source_runs"]}
    assert completed["status"] == "partial_success"
    assert sources == {"failed-fixture": "failed", "working-fixture": "success"}
    assert "source_progress" in events.text
    assert '"event_type":"completed"' in events.text


@pytest.mark.anyio
async def test_candidate_is_persisted_before_source_failure(tmp_path: Path) -> None:
    app = create_app(
        config_path=create_config(tmp_path),
        database_path=tmp_path / "app.db",
        source_adapters=[PartiallyFailedAdapter()],
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        started = await client.post("/api/scans", json={})
        completed = await wait_for_terminal(client, started.json()["job"]["id"])
        properties = await client.get("/api/properties")

    assert completed["status"] == "partial_success"
    assert completed["counters"]["candidates"] == 1
    assert completed["source_runs"][0]["status"] == "partial_failed"
    assert properties.json()["count"] == 1


@pytest.mark.anyio
async def test_startup_marks_unfinished_scan_interrupted(tmp_path: Path) -> None:
    config_path = create_config(tmp_path)
    database_path = tmp_path / "app.db"
    first_app = create_app(config_path=config_path, database_path=database_path)
    async with first_app.router.lifespan_context(first_app):
        from smart_house_hunting.db.models import ScanJob, ScanSourceRun

        with first_app.state.session_factory.begin() as session:
            job = ScanJob(status="running", config_fingerprint="a" * 64, counters={})
            job.source_runs = [ScanSourceRun(source="fixture", status="running", counters={})]
            session.add(job)

    second_app = create_app(config_path=config_path, database_path=database_path)
    async with (
        second_app.router.lifespan_context(second_app),
        AsyncClient(transport=ASGITransport(app=second_app), base_url="http://test") as client,
    ):
        status = await client.get("/api/scans/status")

    assert status.json()["latest_attempt"]["status"] == "interrupted"
    assert status.json()["latest_attempt"]["source_runs"][0]["status"] == "failed"


@pytest.mark.anyio
async def test_fixture_applies_bedroom_and_bathroom_search_filters(tmp_path: Path) -> None:
    config_path = create_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["search"]["minimum_bedrooms"] = 4
    config["search"]["minimum_bathrooms"] = 3
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = create_app(
        config_path=config_path,
        database_path=tmp_path / "app.db",
        source_adapters=fixture_adapters(),
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        started = await client.post("/api/scans", json={})
        completed = await wait_for_terminal(client, started.json()["job"]["id"])
        properties = await client.get("/api/properties")

    assert completed["status"] == "success"
    assert completed["counters"]["candidates"] == 0
    assert properties.json()["count"] == 0
