from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from smart_house_hunting.sources.base import (
    CandidateCallback,
    NormalizedListing,
    ProgressCallback,
    ScanRequest,
    detail_completed_today,
    merge_missing_listing,
)
from smart_house_hunting.sources.payloads import retain_response_payload

ZILLOW_ROOT = "https://www.zillow.com"
PROPERTY_TYPE_FILTERS = {
    "single_family": "isSingleFamily",
    "condo": "isCondo",
    "townhouse": "isTownhouse",
    "multi_family": "isMultiFamily",
    "land": "isLotLand",
    "mobile": "isManufactured",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_ZERO_RESULTS = re.compile(r'\b0\s+(?:homes?|results?)\b|"totalResultCount"\s*:\s*0', re.I)
logger = logging.getLogger(__name__)


class ZillowError(RuntimeError):
    """Base class for sanitized Zillow source failures."""


class ZillowConfigurationError(ZillowError):
    pass


class ZillowAccessBlocked(ZillowError):
    pass


class ZillowLayoutError(ZillowError):
    pass


class ZillowRequestError(ZillowError):
    pass


class ZillowListingUnavailable(ZillowError):
    pass


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._buffer: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag != "script":
            return
        if attributes.get("type") == "application/ld+json" or attributes.get("id") in {
            "__NEXT_DATA__",
            "__NEXT_DATA__script",
        }:
            self._capture = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or not self._capture:
            return
        self._capture = False
        with suppress(json.JSONDecodeError):
            self.documents.append(json.loads("".join(self._buffer)))


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _decimal(value)
    return int(number) if number is not None and number >= 0 else None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _schema_type(node: dict[str, Any], expected: str) -> bool:
    value = node.get("@type")
    return value == expected or isinstance(value, list) and expected in value


def _property_type(value: Any) -> str:
    normalized = str(value or "").replace("-", "_").replace(" ", "_").upper()
    return {
        "SINGLE_FAMILY": "single_family",
        "SINGLEFAMILYRESIDENCE": "single_family",
        "HOUSE": "single_family",
        "CONDO": "condo",
        "CONDOMINIUM": "condo",
        "TOWNHOUSE": "townhouse",
        "MULTI_FAMILY": "multi_family",
        "MULTIFAMILY": "multi_family",
        "LOT": "land",
        "LAND": "land",
        "MANUFACTURED": "mobile",
        "MOBILE": "mobile",
    }.get(normalized, "other")


def _lot_size_sqft(info: dict[str, Any]) -> Decimal | None:
    value = _decimal(info.get("lotAreaValue") or info.get("lotSize"))
    if value is None:
        return None
    unit = str(info.get("lotAreaUnit") or info.get("lotSizeUnit") or "sqft").casefold()
    return value * Decimal("43560") if "acre" in unit else value


def _image_urls(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _sold_history(record: dict[str, Any]) -> list[dict[str, object]]:
    history = record.get("priceHistory") or record.get("price_history") or []
    sold: list[dict[str, object]] = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or item.get("eventType") or item.get("status") or "")
            if "sold" not in event.casefold():
                continue
            price = _decimal(item.get("price") or item.get("salePrice"))
            sold.append(
                {
                    "sale_date": item.get("date") or item.get("eventDate") or item.get("saleDate"),
                    "sale_price": str(price) if price is not None else None,
                    "original_listing_price": str(value)
                    if (value := _decimal(item.get("originalListPrice"))) is not None
                    else None,
                    "final_listing_price": str(value)
                    if (value := _decimal(item.get("lastListPrice"))) is not None
                    else None,
                }
            )
    if not sold:
        price = _decimal(record.get("lastSoldPrice") or record.get("last_sold_price"))
        sold_date = record.get("lastSoldDate") or record.get("last_sold_date")
        if price is not None or sold_date:
            sold.append(
                {
                    "sale_date": sold_date,
                    "sale_price": str(price) if price is not None else None,
                    "original_listing_price": None,
                    "final_listing_price": None,
                }
            )
    return sold


def _status(value: Any) -> str | None:
    normalized = str(value or "").upper()
    if any(word in normalized for word in ("FOR_SALE", "ACTIVE", "COMING_SOON")):
        return "active"
    if "SOLD" in normalized:
        return "sold"
    if any(word in normalized for word in ("OFF_MARKET", "OTHER", "OUT_OF_STOCK")):
        return "off_market"
    return None


def _town_slug(municipality: str, state: str) -> str:
    town = re.sub(r"[^a-z0-9]+", "-", municipality.casefold()).strip("-")
    return f"{town}-{state.casefold()}"


def build_search_url(request: ScanRequest, municipality: str) -> str:
    unsupported = set(request.included_property_types) - set(PROPERTY_TYPE_FILTERS)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ZillowConfigurationError(f"Zillow property filters are unsupported: {names}")
    filter_state: dict[str, Any] = {
        key: {"value": property_type in request.included_property_types}
        for property_type, key in PROPERTY_TYPE_FILTERS.items()
    }
    filter_state.update(
        {
            "price": {"max": int(request.maximum_price)},
            "beds": {"min": float(request.minimum_bedrooms)},
            "baths": {"min": float(request.minimum_bathrooms)},
        }
    )
    query = {
        "usersSearchTerm": f"{municipality}, {request.state.upper()}",
        "filterState": filter_state,
    }
    encoded = quote(json.dumps(query, sort_keys=True, separators=(",", ":")), safe="")
    return f"{ZILLOW_ROOT}/{_town_slug(municipality, request.state)}/?searchQueryState={encoded}"


def _address_parts(record: dict[str, Any], municipality: str) -> tuple[str, str, str, str | None]:
    address = record.get("address")
    if isinstance(address, dict):
        street = address.get("streetAddress") or address.get("addressLine1")
        city = address.get("addressLocality") or address.get("city")
        state = address.get("addressRegion") or address.get("state")
        postal = address.get("postalCode") or address.get("zipcode")
    else:
        street = record.get("addressStreet")
        city = record.get("addressCity")
        state = record.get("addressState")
        postal = record.get("zipcode")
        if not street and isinstance(address, str):
            parts = [part.strip() for part in address.split(",")]
            street = parts[0] if parts else None
            city = parts[1] if len(parts) > 1 else None
            state_zip = parts[2].split() if len(parts) > 2 else []
            state = state_zip[0] if state_zip else None
            postal = state_zip[1] if len(state_zip) > 1 else postal
    return (
        str(street or "").strip(),
        str(city or municipality).strip(),
        str(state or "MA").strip(),
        str(postal) if postal else None,
    )


def _record_to_listing(
    record: dict[str, Any], request: ScanRequest, municipality: str
) -> NormalizedListing | None:
    info = record
    hdp_data = record.get("hdpData")
    if isinstance(hdp_data, dict) and isinstance(hdp_data.get("homeInfo"), dict):
        info = {**record, **hdp_data["homeInfo"]}
    zpid = info.get("zpid") or record.get("zpid")
    url = record.get("detailUrl") or record.get("hdpUrl") or info.get("url")
    if zpid is None or not isinstance(url, str):
        return None
    street, city, state, postal = _address_parts(info, municipality)
    if not street:
        street, city, state, postal = _address_parts(record, municipality)
    if not street:
        return None
    coordinates = info.get("latLong") if isinstance(info.get("latLong"), dict) else {}
    property_type = _property_type(info.get("homeType") or info.get("propertyType"))
    return NormalizedListing(
        source="zillow",
        source_listing_id=str(zpid),
        url=urljoin(ZILLOW_ROOT, url),
        street_address=street,
        municipality=city,
        state=state,
        postal_code=postal,
        latitude=_decimal(coordinates.get("latitude") or info.get("latitude")),
        longitude=_decimal(coordinates.get("longitude") or info.get("longitude")),
        price=_decimal(info.get("price") or record.get("unformattedPrice")),
        status=_status(info.get("homeStatus") or record.get("statusType")) or "active",
        bedrooms=_decimal(info.get("bedrooms") or record.get("beds")),
        bathrooms=_decimal(info.get("bathrooms") or record.get("baths")),
        living_area_sqft=_integer(info.get("livingArea") or record.get("area")),
        lot_size_sqft=_lot_size_sqft(info),
        facts={
            "property_type": property_type,
            "year_built": _integer(info.get("yearBuilt")),
            "image_urls": _image_urls(
                info.get("imgSrc") or record.get("imgSrc") or info.get("image")
            ),
            "sold_history": _sold_history(info),
        },
    )


def _eligible(candidate: NormalizedListing, request: ScanRequest, municipality: str) -> bool:
    return (
        candidate.municipality.casefold() == municipality.casefold()
        and candidate.state.casefold() == request.state.casefold()
        and candidate.facts.get("property_type") in request.included_property_types
        and (candidate.price is None or candidate.price <= request.maximum_price)
        and candidate.bedrooms is not None
        and candidate.bedrooms >= request.minimum_bedrooms
        and candidate.bathrooms is not None
        and candidate.bathrooms >= request.minimum_bathrooms
    )


def parse_search_page(
    html: str, request: ScanRequest, municipality: str
) -> list[NormalizedListing]:
    parser = _ScriptParser()
    parser.feed(html)
    candidates: list[NormalizedListing] = []
    seen: set[str] = set()
    for document in parser.documents:
        for node in _walk(document):
            if not isinstance(node, dict):
                continue
            candidate = _record_to_listing(node, request, municipality)
            if candidate is None or candidate.source_listing_id in seen:
                continue
            if not _eligible(candidate, request, municipality):
                continue
            seen.add(candidate.source_listing_id)
            candidates.append(candidate)
    if not candidates and not _ZERO_RESULTS.search(html):
        raise ZillowLayoutError("Zillow search page contained no parseable matching listings")
    return candidates


def parse_detail_page(html: str, fallback: NormalizedListing) -> NormalizedListing:
    parser = _ScriptParser()
    parser.feed(html)
    listing: dict[str, Any] | None = None
    residence: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    for document in parser.documents:
        for node in _walk(document):
            if not isinstance(node, dict):
                continue
            if str(node.get("zpid", "")) == fallback.source_listing_id and (
                record is None or len(node) > len(record)
            ):
                record = node
            if _schema_type(node, "RealEstateListing") or _schema_type(node, "Product"):
                node_url = str(node.get("url", "")).rstrip("/")
                if not node_url or node_url == fallback.url.rstrip("/"):
                    listing = node
            if _schema_type(node, "SingleFamilyResidence"):
                residence = node
    if record is not None:
        request = ScanRequest(
            municipalities=[fallback.municipality],
            included_property_types=[str(fallback.facts.get("property_type", "single_family"))],
            maximum_price=Decimal("999999999"),
        )
        parsed = _record_to_listing(record, request, fallback.municipality)
        if parsed is not None:
            return fallback.model_copy(
                update={
                    **parsed.model_dump(exclude={"source", "source_listing_id", "url"}),
                    "facts": {**fallback.facts, **parsed.facts},
                }
            )
    if listing is not None and residence is None:
        main_entity = listing.get("mainEntity")
        if isinstance(main_entity, dict):
            residence = main_entity
    if listing is None and residence is None:
        raise ZillowLayoutError("Zillow detail page contained no matching structured listing")
    listing = listing or {}
    residence = residence or {}
    address = residence.get("address") if isinstance(residence.get("address"), dict) else {}
    geo = residence.get("geo") if isinstance(residence.get("geo"), dict) else {}
    floor = residence.get("floorSize") if isinstance(residence.get("floorSize"), dict) else {}
    offer = listing.get("offers") if isinstance(listing.get("offers"), dict) else {}
    property_type = _property_type(residence.get("@type") or residence.get("homeType"))
    if property_type == "other":
        property_type = str(fallback.facts.get("property_type", "other"))
    images = _image_urls(residence.get("image") or listing.get("image"))
    return fallback.model_copy(
        update={
            "street_address": str(address.get("streetAddress") or fallback.street_address),
            "municipality": str(address.get("addressLocality") or fallback.municipality),
            "state": str(address.get("addressRegion") or fallback.state),
            "postal_code": str(address.get("postalCode") or fallback.postal_code),
            "latitude": _decimal(geo.get("latitude")) or fallback.latitude,
            "longitude": _decimal(geo.get("longitude")) or fallback.longitude,
            "price": _decimal(offer.get("price")) or fallback.price,
            "status": _status(offer.get("availability")) or fallback.status,
            "bedrooms": _decimal(residence.get("numberOfBedrooms")) or fallback.bedrooms,
            "bathrooms": _decimal(residence.get("numberOfBathroomsTotal")) or fallback.bathrooms,
            "living_area_sqft": _integer(floor.get("value")) or fallback.living_area_sqft,
            "lot_size_sqft": fallback.lot_size_sqft,
            "description": str(listing.get("description") or "") or fallback.description,
            "facts": {
                **fallback.facts,
                "property_type": property_type,
                "year_built": _integer(residence.get("yearBuilt")),
                "image_urls": images,
                "raw_crawled_data": {"listing": listing, "residence": residence},
            },
            "source_updated_at": _datetime(listing.get("dateModified")),
        }
    )


def _blocked(response: httpx.Response) -> bool:
    sample = response.text[:20_000].casefold()
    final_url = str(response.url).casefold()
    return (
        response.status_code in {403, 429}
        or response.headers.get("x-px-blocked") == "1"
        or "captcha" in final_url
        or "access to this page has been denied" in sample
        or "px-captcha" in sample
        or "perimeterx" in sample
    )


def _reuse_detail(current: NormalizedListing, previous: NormalizedListing) -> NormalizedListing:
    return merge_missing_listing(current, previous)


class ZillowSourceAdapter:
    name = "zillow"
    parser_version = "zillow-embedded-json-v1"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        minimum_interval_seconds: float = 5,
        maximum_interval_seconds: float = 10,
        max_attempts: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._minimum_interval = minimum_interval_seconds
        self._maximum_interval = maximum_interval_seconds
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._retain_payloads = False

    async def _pace(self) -> None:
        if self._last_request_at is None:
            return
        interval = random.uniform(self._minimum_interval, self._maximum_interval)
        remaining = interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            logger.info("zillow rate-limit wait seconds=%.1f", remaining)
            await self._sleep(remaining)

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        for attempt in range(self._max_attempts):
            await self._pace()
            self._last_request_at = time.monotonic()
            started_at = time.monotonic()
            path = urlparse(url).path
            logger.info(
                "zillow request started path=%s attempt=%s/%s",
                path,
                attempt + 1,
                self._max_attempts,
            )
            try:
                response = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                logger.warning(
                    "zillow request error path=%s attempt=%s error_type=%s",
                    path,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt + 1 == self._max_attempts:
                    raise ZillowRequestError(
                        "Zillow request failed after bounded retries"
                    ) from error
                await self._sleep(2**attempt)
                continue
            logger.info(
                "zillow response path=%s status=%s bytes=%s elapsed_seconds=%.2f",
                path,
                response.status_code,
                len(response.content),
                time.monotonic() - started_at,
            )
            retain_response_payload("zillow", response, enabled=self._retain_payloads)
            if _blocked(response):
                logger.error("zillow access blocked path=%s status=%s", path, response.status_code)
                raise ZillowAccessBlocked("Zillow blocked the request; scanning stopped")
            if response.status_code == 404:
                raise ZillowListingUnavailable("Zillow listing is no longer available")
            if response.status_code >= 500 and attempt + 1 < self._max_attempts:
                await self._sleep(2**attempt)
                continue
            if response.is_error:
                raise ZillowRequestError(f"Zillow returned HTTP {response.status_code}")
            return response.text
        raise ZillowRequestError("Zillow request failed")

    async def scan(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
        on_candidate: CandidateCallback | None = None,
    ) -> list[NormalizedListing]:
        self._retain_payloads = request.retain_source_payloads
        urls = [(town, build_search_url(request, town)) for town in request.municipalities]
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            timeout=httpx.Timeout(20),
        )
        results: list[NormalizedListing] = []
        discovered: set[str] = set()
        previous_by_id = {
            listing.source_listing_id: listing for listing in request.tracked_listings
        }
        try:
            for town_index, (municipality, url) in enumerate(urls, start=1):
                await progress(
                    "municipality_started",
                    {"municipality": municipality, "current": town_index, "total": len(urls)},
                )
                search_html = await self._get(client, url)
                candidates = parse_search_page(search_html, request, municipality)
                logger.info(
                    "zillow listings discovered municipality=%s count=%s",
                    municipality,
                    len(candidates),
                )
                await progress(
                    "listings_discovered", {"municipality": municipality, "count": len(candidates)}
                )
                succeeded = 0
                failed = 0
                skipped = 0
                for index, candidate in enumerate(candidates, start=1):
                    discovered.add(candidate.source_listing_id)
                    await progress(
                        "listing_started",
                        {
                            "municipality": municipality,
                            "current": succeeded + failed + skipped,
                            "total": len(candidates),
                            "succeeded": succeeded,
                            "failed": failed,
                            "skipped": skipped,
                            "in_progress": 1,
                        },
                    )
                    detail_failed = False
                    detail_reused = False
                    previous = previous_by_id.get(candidate.source_listing_id)
                    if (
                        previous is not None
                        and detail_completed_today(previous)
                        and not request.force_refresh
                    ):
                        detail_reused = True
                        detailed = _reuse_detail(candidate, previous)
                    else:
                        try:
                            detail_html = await self._get(client, candidate.url)
                            detailed = parse_detail_page(detail_html, candidate)
                        except ZillowAccessBlocked:
                            raise
                        except (
                            ZillowLayoutError,
                            ZillowListingUnavailable,
                            ZillowRequestError,
                        ) as error:
                            detail_failed = True
                            logger.warning(
                                "zillow detail degraded municipality=%s listing_id=%s "
                                "progress=%s/%s error_type=%s",
                                municipality,
                                candidate.source_listing_id,
                                index,
                                len(candidates),
                                type(error).__name__,
                            )
                            detailed = candidate.model_copy(
                                update={
                                    "facts": {
                                        **candidate.facts,
                                        "detail_error": type(error).__name__,
                                    }
                                }
                            )
                    if previous is not None:
                        detailed = merge_missing_listing(detailed, previous)
                    results.append(detailed)
                    if on_candidate is not None:
                        await on_candidate(detailed)
                    if detail_failed:
                        failed += 1
                        event = "listing_detail_failed"
                    elif detail_reused:
                        skipped += 1
                        event = "listing_reused"
                    else:
                        succeeded += 1
                        event = "listing_completed"
                    await progress(
                        event,
                        {
                            "municipality": municipality,
                            "current": succeeded + failed + skipped,
                            "total": len(candidates),
                            "succeeded": succeeded,
                            "failed": failed,
                            "skipped": skipped,
                            "in_progress": 0,
                        },
                    )
                await progress(
                    "municipality_completed",
                    {"municipality": municipality, "current": town_index, "total": len(urls)},
                )
            tracked = [
                listing
                for listing in request.tracked_listings
                if listing.source_listing_id not in discovered
                and listing.municipality.casefold()
                in {town.casefold() for town in request.municipalities}
            ]
            if tracked:
                await progress("tracked_refresh_started", {"count": len(tracked)})
            for index, candidate in enumerate(tracked, start=1):
                try:
                    detail_html = await self._get(client, candidate.url)
                except ZillowListingUnavailable:
                    detailed = candidate.model_copy(
                        update={
                            "status": "unavailable",
                            "facts": {**candidate.facts, "unavailable_reason": "http_404"},
                        }
                    )
                else:
                    detailed = parse_detail_page(detail_html, candidate)
                results.append(detailed)
                if on_candidate is not None:
                    await on_candidate(detailed)
                await progress(
                    "tracked_listing_completed", {"current": index, "total": len(tracked)}
                )
        finally:
            if owns_client:
                await client.aclose()
        return results
