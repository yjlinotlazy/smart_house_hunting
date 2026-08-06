from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from smart_house_hunting.sources.base import (
    NormalizedListing,
    ScanRequest,
    merge_missing_listing,
)
from smart_house_hunting.sources.redfin import (
    RedfinAccessBlocked,
    RedfinLayoutError,
    RedfinSourceAdapter,
    RedfinWafChallenge,
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
    assert build_search_url(request(), "Belmont") == (
        "https://www.redfin.com/city/36093/MA/Belmont/filter/"
        "property-type=house,max-price=2M,min-beds=3,min-baths=2"
    )


def test_parses_search_and_detail_json_ld() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")
    candidates = parse_search_page(search_html, request(), "Belmont")

    assert len(candidates) == 1
    assert candidates[0].source_listing_id == "100001"
    assert candidates[0].price == Decimal("900000")
    assert candidates[0].facts["image_urls"] == ["https://images.example.invalid/redfin-search.jpg"]
    assert candidates[0].bedrooms == Decimal("3")
    assert candidates[0].bathrooms == Decimal("2.5")

    detail_html = (FIXTURES / "redfin_detail.html").read_text(encoding="utf-8")
    detailed = parse_detail_page(detail_html, candidates[0])

    assert detailed.price == Decimal("895000")
    assert detailed.living_area_sqft == 1850
    assert detailed.lot_size_sqft == Decimal("10890.00")
    assert detailed.facts["year_built"] == 1940
    assert detailed.description == "Sanitized listing description."
    assert detailed.source_updated_at is not None


def test_layout_change_is_not_an_empty_success() -> None:
    with pytest.raises(RedfinLayoutError):
        parse_search_page("<html><body>changed layout</body></html>", request(), "Belmont")


def test_card_without_json_ld_is_retained_as_a_manual_link() -> None:
    html = """
    <div data-rf-test-name="basicNode-homeCard">
      <a class="bp-Homecard__Address" href="/MA/Belmont/30-Example-Rd-02478/home/100003">
        30 Example Rd, Belmont, MA 02478
      </a>
    </div>
    """

    candidates = parse_search_page(html, request(), "Belmont")

    assert len(candidates) == 1
    assert candidates[0].url.endswith("/home/100003")
    assert candidates[0].facts["detail_error"] == "RedfinSearchStructuredDataMissing"


@pytest.mark.anyio
async def test_adapter_stops_immediately_on_robot_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="<title>Are You a Robot?</title>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        with pytest.raises(RedfinAccessBlocked):
            await adapter.scan(request(), progress)

    assert calls == 1


@pytest.mark.anyio
async def test_adapter_discovers_and_enriches_listing_offline() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "redfin_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        html = detail_html if "/home/" in request.url.path else search_html
        return httpx.Response(200, text=html)

    events: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(event: str, _payload: dict[str, object]) -> None:
            events.append(event)

        candidates = await adapter.scan(request(), progress)

    assert len(candidates) == 1
    assert candidates[0].price == Decimal("895000")
    assert "listings_discovered" in events
    assert "listing_completed" in events


@pytest.mark.anyio
async def test_detail_waf_challenge_persists_fallback_then_stops_source() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")

    def handler(http_request: httpx.Request) -> httpx.Response:
        if "/home/" in http_request.url.path:
            return httpx.Response(
                202,
                text="<script>window.awsWafCookieDomainList=[]; window.gokuProps={};</script>",
            )
        return httpx.Response(200, text=search_html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        persisted = []

        async def on_candidate(candidate) -> None:
            persisted.append(candidate)

        with pytest.raises(RedfinWafChallenge):
            await adapter.scan(request(), progress, on_candidate)

    assert len(persisted) == 1
    assert persisted[0].facts["detail_error"] == "RedfinWafChallenge"
    assert persisted[0].facts["image_urls"] == ["https://images.example.invalid/redfin-search.jpg"]


@pytest.mark.anyio
async def test_adapter_reuses_successful_detail_from_the_same_day() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "redfin_detail.html").read_text(encoding="utf-8")
    prior = parse_detail_page(
        detail_html,
        parse_search_page(search_html, request(), "Belmont")[0],
    ).model_copy(update={"last_observed_at": datetime.now(UTC)})
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=search_html)

    reused_request = request().model_copy(update={"tracked_listings": [prior]})
    events: list[str] = []
    payloads: list[dict[str, object]] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(event: str, payload: dict[str, object]) -> None:
            events.append(event)
            payloads.append(payload)

        candidates = await adapter.scan(reused_request, progress)

    assert calls == 1
    assert len(candidates) == 1
    assert candidates[0].facts["year_built"] == 1940
    assert candidates[0].facts["sold_history"][0]["sale_price"] == "825000"
    assert "listing_reused" in events
    reused = payloads[events.index("listing_reused")]
    assert reused["skipped"] == 1
    assert reused["succeeded"] == 0


def test_new_listing_data_overrides_old_but_retains_missing_fields() -> None:
    previous = NormalizedListing(
        source="redfin",
        source_listing_id="one",
        url="https://example.invalid/old",
        street_address="10 Example Rd",
        municipality="Belmont",
        price=Decimal("900000"),
        lot_size_sqft=Decimal("10890"),
        description="Old complete description",
        facts={"property_type": "single_family", "detail_error": "OldError"},
    )
    current = previous.model_copy(
        update={
            "url": "https://example.invalid/new",
            "price": Decimal("875000"),
            "lot_size_sqft": None,
            "description": None,
            "facts": {"property_type": "single_family", "year_built": 1940},
        }
    )

    merged = merge_missing_listing(current, previous)

    assert merged.price == Decimal("875000")
    assert merged.lot_size_sqft == Decimal("10890")
    assert merged.description == "Old complete description"
    assert merged.facts["year_built"] == 1940
    assert "detail_error" not in merged.facts


@pytest.mark.anyio
async def test_force_refresh_does_not_reuse_same_day_detail() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "redfin_detail.html").read_text(encoding="utf-8")
    prior = parse_detail_page(
        detail_html,
        parse_search_page(search_html, request(), "Belmont")[0],
    ).model_copy(update={"last_observed_at": datetime.now(UTC)})
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        html = detail_html if "/home/" in http_request.url.path else search_html
        return httpx.Response(200, text=html)

    forced_request = request().model_copy(
        update={"tracked_listings": [prior], "force_refresh": True}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        candidates = await adapter.scan(forced_request, progress)

    assert calls == 2
    assert candidates[0].lot_size_sqft == Decimal("10890.00")


@pytest.mark.anyio
async def test_adapter_marks_missing_tracked_listing_unavailable() -> None:
    search_html = (FIXTURES / "redfin_search.html").read_text(encoding="utf-8")
    tracked = parse_search_page(search_html, request(), "Belmont")[0]

    def handler(http_request: httpx.Request) -> httpx.Response:
        if "/home/" in http_request.url.path:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text="<html><body>0 homes</body></html>")

    scan_request = request().model_copy(update={"tracked_listings": [tracked]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RedfinSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        candidates = await adapter.scan(scan_request, progress)

    assert len(candidates) == 1
    assert candidates[0].status == "unavailable"
    assert candidates[0].facts["unavailable_reason"] == "http_404"
