from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from smart_house_hunting.sources.base import ScanRequest
from smart_house_hunting.sources.realtor import (
    RealtorAccessBlocked,
    RealtorLayoutError,
    RealtorSourceAdapter,
    build_search_url,
    build_sold_search_url,
    parse_detail_page,
    parse_search_page,
    parse_sold_search_page,
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
        "https://www.realtor.com/realestateandhomes-search/Belmont_MA/"
        "type-single-family-home/beds-3/baths-2/price-na-2000000"
    )

    assert build_sold_search_url(request(), "Belmont") == (
        "https://www.realtor.com/realestateandhomes-search/Belmont_MA/"
        "show-recently-sold/type-single-family-home/beds-3/baths-2"
    )


def test_parses_sold_search_records_without_treating_them_as_active() -> None:
    html = (FIXTURES / "realtor_sold_search.html").read_text(encoding="utf-8")

    sold = parse_sold_search_page(html, request(), "Belmont")

    assert len(sold) == 1
    assert sold[0].status == "sold"
    assert sold[0].price == Decimal("825000")
    assert sold[0].facts["record_kind"] == "sold_comparable"
    assert sold[0].facts["sold_history"][0]["sale_price"] == "825000"


def test_parses_search_and_detail_structured_data() -> None:
    search_html = (FIXTURES / "realtor_search.html").read_text(encoding="utf-8")
    candidates = parse_search_page(search_html, request(), "Belmont")

    assert len(candidates) == 1
    assert candidates[0].source == "realtor"
    assert candidates[0].source_listing_id == "M10000-00001"
    assert candidates[0].price == Decimal("900000")
    assert candidates[0].bedrooms == Decimal("3")
    assert candidates[0].bathrooms == Decimal("2.5")
    assert candidates[0].lot_size_sqft == Decimal("20037.60")

    detail_html = (FIXTURES / "realtor_detail.html").read_text(encoding="utf-8")
    detailed = parse_detail_page(detail_html, candidates[0])

    assert detailed.price == Decimal("895000")
    assert detailed.living_area_sqft == 1850
    assert detailed.latitude == Decimal("42.1")
    assert detailed.description.startswith("For Sale:")
    assert detailed.facts["year_built"] == 1940
    assert detailed.facts["sold_history"] == [
        {
            "sale_date": "2024-06-11",
            "sale_price": "825000",
            "original_listing_price": None,
            "final_listing_price": None,
        }
    ]


def test_layout_change_is_not_an_empty_success() -> None:
    with pytest.raises(RealtorLayoutError):
        parse_search_page("<html><body>changed layout</body></html>", request(), "Belmont")


@pytest.mark.anyio
async def test_adapter_stops_immediately_on_access_block() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="Access to this page has been denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RealtorSourceAdapter(
            client=client,
            minimum_interval_seconds=0,
            maximum_interval_seconds=0,
        )

        async def progress(_event: str, _payload: dict[str, object]) -> None:
            return None

        with pytest.raises(RealtorAccessBlocked):
            await adapter.scan(request(), progress)

    assert calls == 1


@pytest.mark.anyio
async def test_adapter_discovers_and_enriches_listing_offline() -> None:
    search_html = (FIXTURES / "realtor_search.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "realtor_detail.html").read_text(encoding="utf-8")

    def handler(http_request: httpx.Request) -> httpx.Response:
        if "realestateandhomes-detail" in http_request.url.path:
            return httpx.Response(200, text=detail_html)
        return httpx.Response(200, text=search_html)

    events: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RealtorSourceAdapter(
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
