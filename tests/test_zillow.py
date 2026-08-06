from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from smart_house_hunting.sources.base import ScanRequest
from smart_house_hunting.sources.zillow import (
    ZillowAccessBlocked,
    ZillowLayoutError,
    ZillowSourceAdapter,
    build_search_url,
    parse_detail_page,
    parse_search_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def request() -> ScanRequest:
    return ScanRequest(
        municipalities=["Belmont"],
        included_property_types=["single_family"],
        minimum_bedrooms=Decimal("3"),
        minimum_bathrooms=Decimal("2"),
        maximum_price=Decimal("2000000"),
    )


def test_builds_filtered_town_url() -> None:
    url = build_search_url(request(), "Belmont")
    assert url.startswith("https://www.zillow.com/belmont-ma/")
    state = json.loads(parse_qs(urlparse(url).query)["searchQueryState"][0])
    assert state["usersSearchTerm"] == "Belmont, MA"
    assert state["filterState"]["isSingleFamily"]["value"] is True
    assert state["filterState"]["isCondo"]["value"] is False
    assert state["filterState"]["price"]["max"] == 2_000_000
    assert state["filterState"]["beds"]["min"] == 3
    assert state["filterState"]["baths"]["min"] == 2


def test_parses_search_and_detail_structured_data() -> None:
    search_html = (FIXTURES / "zillow_search.html").read_text(encoding="utf-8")
    candidates = parse_search_page(search_html, request(), "Belmont")

    assert len(candidates) == 1
    assert candidates[0].source == "zillow"
    assert candidates[0].source_listing_id == "200001"
    assert candidates[0].price == Decimal("900000")
    assert candidates[0].facts["property_type"] == "single_family"
    assert candidates[0].lot_size_sqft == Decimal("10890.00")
    assert candidates[0].facts["sold_history"][0]["sale_price"] == "825000"

    detail_html = (FIXTURES / "zillow_detail.html").read_text(encoding="utf-8")
    detailed = parse_detail_page(detail_html, candidates[0])

    assert detailed.price == Decimal("895000")
    assert detailed.living_area_sqft == 1850
    assert detailed.description == "Sanitized Zillow listing description."
    assert detailed.source_updated_at is not None


def test_layout_change_is_not_an_empty_success() -> None:
    with pytest.raises(ZillowLayoutError):
        parse_search_page("<html><body>changed layout</body></html>", request(), "Belmont")


@pytest.mark.anyio
async def test_adapter_stops_immediately_on_perimeterx_block() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            headers={"x-px-blocked": "1"},
            text="<title>Access to this page has been denied</title>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZillowSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        with pytest.raises(ZillowAccessBlocked):
            await adapter.scan(request(), progress)

    assert calls == 1


@pytest.mark.anyio
async def test_adapter_discovers_and_enriches_listing_offline() -> None:
    search_html = (FIXTURES / "zillow_search.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "zillow_detail.html").read_text(encoding="utf-8")

    def handler(http_request: httpx.Request) -> httpx.Response:
        html = detail_html if "/homedetails/" in http_request.url.path else search_html
        return httpx.Response(200, text=html)

    events: list[str] = []
    persisted = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ZillowSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(event: str, _payload: dict[str, object]) -> None:
            events.append(event)

        async def on_candidate(candidate) -> None:
            persisted.append(candidate)

        candidates = await adapter.scan(request(), progress, on_candidate)

    assert len(candidates) == 1
    assert len(persisted) == 1
    assert candidates[0].price == Decimal("895000")
    assert "listings_discovered" in events
    assert "listing_completed" in events
