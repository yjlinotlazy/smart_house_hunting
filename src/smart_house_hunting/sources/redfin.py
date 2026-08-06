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
from urllib.parse import urljoin, urlparse

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

REDFIN_ROOT = "https://www.redfin.com"
REDFIN_TOWNS = {
    ("MA", "belmont"): ("36093", "Belmont"),
    ("MA", "newton"): ("11619", "Newton"),
}
PROPERTY_TYPE_FILTERS = {
    "single_family": "house",
    "condo": "condo",
    "townhouse": "townhouse",
    "multi_family": "multifamily",
    "land": "land",
    "mobile": "mobile",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_LISTING_ID = re.compile(r"/home/(\d+)(?:[/?#]|$)")
_BED_BATH = re.compile(
    r",\s*(?P<beds>\d+(?:\.\d+)?) beds?,\s*(?P<baths>\d+(?:\.\d+)?) baths?",
    re.IGNORECASE,
)
_ZERO_RESULTS = re.compile(r"\b(?:0 homes?|no homes)\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


class RedfinError(RuntimeError):
    """Base class for sanitized Redfin source failures."""


class RedfinConfigurationError(RedfinError):
    pass


class RedfinAccessBlocked(RedfinError):
    pass


class RedfinWafChallenge(RedfinError):
    pass


class RedfinLayoutError(RedfinError):
    pass


class RedfinRequestError(RedfinError):
    pass


class RedfinListingUnavailable(RedfinError):
    pass


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._buffer: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
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


class _SearchCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._current: dict[str, Any] | None = None
        self._address_link = False
        self._address_text: list[str] = []
        self._script = False
        self._script_text: list[str] = []
        self.cards: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._current is None:
            if tag == "div" and attributes.get("data-rf-test-name") == "basicNode-homeCard":
                self._current = {
                    "aria_label": attributes.get("aria-label"),
                    "documents": [],
                }
                self._depth = 1
            return
        if tag == "div":
            self._depth += 1
        classes = (attributes.get("class") or "").split()
        if tag == "img" and "bp-Homecard__Photo--image" in classes:
            if not self._current.get("image_url"):
                self._current["image_url"] = attributes.get("src")
        elif tag == "a" and "bp-Homecard__Address" in classes:
            self._current["href"] = attributes.get("href")
            self._address_link = True
            self._address_text = []
        elif tag == "script" and attributes.get("type") == "application/ld+json":
            self._script = True
            self._script_text = []

    def handle_data(self, data: str) -> None:
        if self._address_link:
            self._address_text.append(data)
        if self._script:
            self._script_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "a" and self._address_link:
            self._address_link = False
            self._current["address_text"] = "".join(self._address_text).strip()
        elif tag == "script" and self._script:
            self._script = False
            with suppress(json.JSONDecodeError):
                self._current["documents"].append(json.loads("".join(self._script_text)))
        if tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self.cards.append(self._current)
                self._current = None


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


def _property_type(node: dict[str, Any]) -> str:
    if _schema_type(node, "SingleFamilyResidence"):
        return "single_family"
    category = str(node.get("accommodationCategory", "")).casefold()
    if "single family" in category:
        return "single_family"
    if "condo" in category:
        return "condo"
    if "townhouse" in category:
        return "townhouse"
    if "multi" in category:
        return "multi_family"
    return "other"


def _area_sqft(value: Any) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    area = _decimal(value.get("value"))
    if area is None:
        return None
    unit = str(value.get("unitText") or value.get("unitCode") or "sqft").casefold()
    return area * Decimal("43560") if "acre" in unit else area


def _sold_history(*nodes: dict[str, Any]) -> list[dict[str, object]]:
    sold: list[dict[str, object]] = []
    for node in nodes:
        history = node.get("priceHistory") or node.get("price_history") or []
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
                        "sale_date": item.get("date")
                        or item.get("eventDate")
                        or item.get("saleDate"),
                        "sale_price": str(price) if price is not None else None,
                        "original_listing_price": str(value)
                        if (value := _decimal(item.get("originalListPrice"))) is not None
                        else None,
                        "final_listing_price": str(value)
                        if (value := _decimal(item.get("lastListPrice"))) is not None
                        else None,
                    }
                )
        price = _decimal(node.get("lastSoldPrice") or node.get("last_sold_price"))
        sold_date = node.get("lastSoldDate") or node.get("last_sold_date")
        if not sold and (price is not None or sold_date):
            sold.append(
                {
                    "sale_date": sold_date,
                    "sale_price": str(price) if price is not None else None,
                    "original_listing_price": None,
                    "final_listing_price": None,
                }
            )
    return sold


def _listing_id(url: str) -> str:
    match = _LISTING_ID.search(url)
    if match is None:
        raise RedfinLayoutError("Redfin listing URL does not contain a listing ID")
    return match.group(1)


def _compact_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _compact_price(value: Decimal) -> str:
    if value % Decimal("1000000") == 0:
        return f"{_compact_decimal(value / Decimal('1000000'))}M"
    if value % Decimal("1000") == 0:
        return f"{_compact_decimal(value / Decimal('1000'))}k"
    return _compact_decimal(value)


def build_search_url(request: ScanRequest, municipality: str) -> str:
    town = REDFIN_TOWNS.get((request.state.upper(), municipality.casefold()))
    if town is None:
        raise RedfinConfigurationError(
            f"Redfin town mapping is not configured for {municipality}, {request.state}"
        )
    unsupported = set(request.included_property_types) - set(PROPERTY_TYPE_FILTERS)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise RedfinConfigurationError(f"Redfin property filters are unsupported: {names}")
    types = "+".join(PROPERTY_TYPE_FILTERS[item] for item in request.included_property_types)
    filters = [f"property-type={types}"]
    filters.append(f"max-price={_compact_price(request.maximum_price)}")
    if request.minimum_bedrooms:
        filters.append(f"min-beds={_compact_decimal(request.minimum_bedrooms)}")
    if request.minimum_bathrooms:
        filters.append(f"min-baths={_compact_decimal(request.minimum_bathrooms)}")
    city_id, canonical_name = town
    return (
        f"{REDFIN_ROOT}/city/{city_id}/{request.state.upper()}/{canonical_name}/filter/"
        + ",".join(filters)
    )


def _from_search_card(
    card: dict[str, Any], request: ScanRequest, requested_municipality: str
) -> NormalizedListing | None:
    href = card.get("href")
    if not isinstance(href, str):
        return None
    url = urljoin(REDFIN_ROOT, href)
    residence: dict[str, Any] | None = None
    product: dict[str, Any] | None = None
    for document in card["documents"]:
        for node in _walk(document):
            if not isinstance(node, dict):
                continue
            if residence is None and _schema_type(node, "SingleFamilyResidence"):
                residence = node
            if product is None and _schema_type(node, "Product"):
                product = node
    address_text = str(card.get("address_text") or "").strip()
    address_parts = [part.strip() for part in address_text.split(",")]
    fallback_municipality = address_parts[-2] if len(address_parts) >= 3 else requested_municipality
    fallback_street = address_parts[0] if address_parts else f"Redfin listing {_listing_id(url)}"
    address = (
        residence.get("address")
        if residence is not None and isinstance(residence.get("address"), dict)
        else {}
    )
    geo = (
        residence.get("geo")
        if residence is not None and isinstance(residence.get("geo"), dict)
        else {}
    )
    floor = (
        residence.get("floorSize")
        if residence is not None and isinstance(residence.get("floorSize"), dict)
        else {}
    )
    offer = product.get("offers") if product and isinstance(product.get("offers"), dict) else {}
    bedrooms = None
    bathrooms = None
    label = card.get("aria_label")
    if isinstance(label, str) and (match := _BED_BATH.search(label)):
        bedrooms = _decimal(match.group("beds"))
        bathrooms = _decimal(match.group("baths"))
    bedrooms = bedrooms or _decimal(residence.get("numberOfBedrooms") if residence else None)
    bathrooms = bathrooms or _decimal(
        residence.get("numberOfBathroomsTotal") if residence else None
    )
    assumed_type = (
        request.included_property_types[0] if len(request.included_property_types) == 1 else "other"
    )
    image_url = card.get("image_url")
    facts = {
        "property_type": _property_type(residence) if residence else assumed_type,
        "image_urls": [image_url] if isinstance(image_url, str) and image_url else [],
    }
    if residence is None:
        facts["detail_error"] = "RedfinSearchStructuredDataMissing"
    return NormalizedListing(
        source="redfin",
        source_listing_id=_listing_id(url),
        url=url,
        street_address=str(address.get("streetAddress") or fallback_street),
        municipality=str(address.get("addressLocality") or fallback_municipality),
        state=str(address.get("addressRegion") or "MA"),
        postal_code=str(address["postalCode"]) if address.get("postalCode") else None,
        latitude=_decimal(geo.get("latitude")),
        longitude=_decimal(geo.get("longitude")),
        price=_decimal(offer.get("price")),
        status="active",
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        living_area_sqft=_integer(floor.get("value")),
        lot_size_sqft=_area_sqft(residence.get("lotSize") if residence else None),
        facts=facts,
    )


def parse_search_page(
    html: str, request: ScanRequest, municipality: str
) -> list[NormalizedListing]:
    parser = _SearchCardParser()
    parser.feed(html)
    candidates: list[NormalizedListing] = []
    seen: set[str] = set()
    for card in parser.cards:
        candidate = _from_search_card(card, request, municipality)
        if candidate is None or candidate.source_listing_id in seen:
            continue
        if candidate.municipality.casefold() != municipality.casefold():
            continue
        if candidate.state.casefold() != request.state.casefold():
            continue
        if candidate.facts.get("property_type") not in request.included_property_types:
            continue
        if candidate.price is not None and candidate.price > request.maximum_price:
            continue
        if not candidate.facts.get("detail_error"):
            if candidate.bedrooms is None or candidate.bedrooms < request.minimum_bedrooms:
                continue
            if candidate.bathrooms is None or candidate.bathrooms < request.minimum_bathrooms:
                continue
        seen.add(candidate.source_listing_id)
        candidates.append(candidate)
    if not candidates and not _ZERO_RESULTS.search(html):
        raise RedfinLayoutError("Redfin search page contained no parseable matching listings")
    return candidates


def parse_detail_page(html: str, fallback: NormalizedListing) -> NormalizedListing:
    parser = _JsonLdParser()
    parser.feed(html)
    listing: dict[str, Any] | None = None
    for document in parser.documents:
        for node in _walk(document):
            if not isinstance(node, dict) or not _schema_type(node, "RealEstateListing"):
                continue
            if str(node.get("url", "")).rstrip("/") == fallback.url.rstrip("/"):
                listing = node
                break
        if listing is not None:
            break
    if listing is None:
        raise RedfinLayoutError("Redfin detail page contained no matching structured listing")
    residence = listing.get("mainEntity")
    if not isinstance(residence, dict):
        raise RedfinLayoutError("Redfin detail page omitted the residence details")
    address = residence.get("address") if isinstance(residence.get("address"), dict) else {}
    geo = residence.get("geo") if isinstance(residence.get("geo"), dict) else {}
    floor = residence.get("floorSize") if isinstance(residence.get("floorSize"), dict) else {}
    offer = listing.get("offers") if isinstance(listing.get("offers"), dict) else {}
    images = residence.get("image") if isinstance(residence.get("image"), list) else []
    image_urls = [item.get("url") for item in images if isinstance(item, dict) and item.get("url")]
    facts = {
        **{key: value for key, value in fallback.facts.items() if key != "detail_error"},
        "property_type": _property_type(residence),
        "year_built": _integer(residence.get("yearBuilt")),
        "date_posted": listing.get("datePosted"),
        "image_urls": image_urls,
        "sold_history": _sold_history(listing, residence),
        "amenities": [
            item.get("name")
            for item in residence.get("amenityFeature", [])
            if isinstance(item, dict) and item.get("value") is True and item.get("name")
        ],
    }
    availability = str(offer.get("availability", ""))
    if availability.endswith("InStock"):
        status = "active"
    elif availability.endswith(("SoldOut", "OutOfStock")):
        status = "off_market"
    else:
        status = fallback.status
    return fallback.model_copy(
        update={
            "street_address": str(address.get("streetAddress") or fallback.street_address),
            "municipality": str(address.get("addressLocality") or fallback.municipality),
            "state": str(address.get("addressRegion") or fallback.state),
            "postal_code": str(address.get("postalCode") or fallback.postal_code),
            "latitude": _decimal(geo.get("latitude")) or fallback.latitude,
            "longitude": _decimal(geo.get("longitude")) or fallback.longitude,
            "price": _decimal(offer.get("price")) or fallback.price,
            "status": status,
            "bedrooms": _decimal(residence.get("numberOfBedrooms")) or fallback.bedrooms,
            "bathrooms": _decimal(residence.get("numberOfBathroomsTotal")) or fallback.bathrooms,
            "living_area_sqft": _integer(floor.get("value")) or fallback.living_area_sqft,
            "lot_size_sqft": _area_sqft(residence.get("lotSize")) or fallback.lot_size_sqft,
            "description": str(listing.get("description") or "") or fallback.description,
            "facts": facts,
            "source_updated_at": _datetime(listing.get("lastReviewed")),
        }
    )


def _blocked(response: httpx.Response) -> bool:
    final_host = urlparse(str(response.url)).hostname or ""
    sample = response.text[:20_000].casefold()
    return (
        response.status_code in {403, 429}
        or final_host == "ratelimited.redfin.com"
        or "are you a robot" in sample
        or "px-captcha" in sample
    )


def _waf_challenge(response: httpx.Response) -> bool:
    sample = response.text[:20_000].casefold()
    return response.status_code == 202 and (
        "awswafcookiedomainlist" in sample or "window.gokuprops" in sample
    )


def _reuse_detail(current: NormalizedListing, previous: NormalizedListing) -> NormalizedListing:
    return merge_missing_listing(current, previous)


class RedfinSourceAdapter:
    name = "redfin"
    parser_version = "redfin-jsonld-v1"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        minimum_interval_seconds: float = 3,
        maximum_interval_seconds: float = 8,
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
            logger.info("redfin rate-limit wait seconds=%.1f", remaining)
            await self._sleep(remaining)

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        for attempt in range(self._max_attempts):
            await self._pace()
            self._last_request_at = time.monotonic()
            started_at = time.monotonic()
            path = urlparse(url).path
            logger.info(
                "redfin request started path=%s attempt=%s/%s",
                path,
                attempt + 1,
                self._max_attempts,
            )
            try:
                response = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                logger.warning(
                    "redfin request error path=%s attempt=%s error_type=%s",
                    path,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt + 1 == self._max_attempts:
                    raise RedfinRequestError(
                        "Redfin request failed after bounded retries"
                    ) from error
                await self._sleep(2**attempt)
                continue
            logger.info(
                "redfin response path=%s status=%s bytes=%s elapsed_seconds=%.2f",
                path,
                response.status_code,
                len(response.content),
                time.monotonic() - started_at,
            )
            retain_response_payload("redfin", response, enabled=self._retain_payloads)
            if _blocked(response):
                logger.error("redfin access blocked path=%s status=%s", path, response.status_code)
                raise RedfinAccessBlocked("Redfin blocked the request; scanning stopped")
            if _waf_challenge(response):
                logger.warning("redfin WAF challenge path=%s status=%s", path, response.status_code)
                raise RedfinWafChallenge("Redfin returned an AWS WAF challenge page")
            if response.status_code == 404:
                raise RedfinListingUnavailable("Redfin listing is no longer available")
            if response.status_code >= 500 and attempt + 1 < self._max_attempts:
                await self._sleep(2**attempt)
                continue
            if response.is_error:
                raise RedfinRequestError(f"Redfin returned HTTP {response.status_code}")
            return response.text
        raise RedfinRequestError("Redfin request failed")

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
            for index, (municipality, url) in enumerate(urls, start=1):
                await progress(
                    "municipality_started",
                    {"municipality": municipality, "current": index, "total": len(urls)},
                )
                search_html = await self._get(client, url)
                candidates = parse_search_page(search_html, request, municipality)
                logger.info(
                    "redfin listings discovered municipality=%s count=%s",
                    municipality,
                    len(candidates),
                )
                await progress(
                    "listings_discovered",
                    {"municipality": municipality, "count": len(candidates)},
                )
                detail_successes = 0
                detail_failures = 0
                detail_skipped = 0
                for detail_index, candidate in enumerate(candidates, start=1):
                    discovered.add(candidate.source_listing_id)
                    await progress(
                        "listing_started",
                        {
                            "municipality": municipality,
                            "current": detail_successes + detail_failures + detail_skipped,
                            "total": len(candidates),
                            "succeeded": detail_successes,
                            "failed": detail_failures,
                            "skipped": detail_skipped,
                            "in_progress": 1,
                        },
                    )
                    detail_failed = False
                    detail_reused = False
                    terminal_waf_error: RedfinWafChallenge | None = None
                    previous = previous_by_id.get(candidate.source_listing_id)
                    if (
                        previous is not None
                        and detail_completed_today(previous)
                        and not request.force_refresh
                    ):
                        detail_reused = True
                        detailed = _reuse_detail(candidate, previous)
                        logger.info(
                            "redfin detail reused municipality=%s listing_id=%s progress=%s/%s",
                            municipality,
                            candidate.source_listing_id,
                            detail_index,
                            len(candidates),
                        )
                    else:
                        try:
                            detail_html = await self._get(client, candidate.url)
                            detailed = parse_detail_page(detail_html, candidate)
                        except RedfinAccessBlocked:
                            raise
                        except (
                            RedfinLayoutError,
                            RedfinListingUnavailable,
                            RedfinRequestError,
                            RedfinWafChallenge,
                        ) as error:
                            detail_failed = True
                            if isinstance(error, RedfinWafChallenge):
                                terminal_waf_error = error
                            logger.warning(
                                "redfin detail degraded municipality=%s listing_id=%s "
                                "progress=%s/%s error_type=%s",
                                municipality,
                                candidate.source_listing_id,
                                detail_index,
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
                    eligible = (
                        detailed.facts.get("property_type") in request.included_property_types
                        and (detailed.price is None or detailed.price <= request.maximum_price)
                        and (
                            bool(detailed.facts.get("detail_error"))
                            or (
                                detailed.bedrooms is not None
                                and detailed.bedrooms >= request.minimum_bedrooms
                                and detailed.bathrooms is not None
                                and detailed.bathrooms >= request.minimum_bathrooms
                            )
                        )
                    )
                    if eligible:
                        results.append(detailed)
                        if on_candidate is not None:
                            await on_candidate(detailed)
                    logger.info(
                        "redfin detail completed municipality=%s listing_id=%s progress=%s/%s",
                        municipality,
                        detailed.source_listing_id,
                        detail_index,
                        len(candidates),
                    )
                    if detail_failed:
                        detail_failures += 1
                        event_type = "listing_detail_failed"
                    elif detail_reused:
                        detail_skipped += 1
                        event_type = "listing_reused"
                    else:
                        detail_successes += 1
                        event_type = "listing_completed"
                    await progress(
                        event_type,
                        {
                            "municipality": municipality,
                            "current": detail_successes + detail_failures + detail_skipped,
                            "total": len(candidates),
                            "succeeded": detail_successes,
                            "failed": detail_failures,
                            "skipped": detail_skipped,
                            "in_progress": 0,
                        },
                    )
                    if terminal_waf_error is not None:
                        raise terminal_waf_error
                await progress(
                    "municipality_completed",
                    {"municipality": municipality, "current": index, "total": len(urls)},
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
                except RedfinListingUnavailable:
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
                    "tracked_listing_completed",
                    {"current": index, "total": len(tracked)},
                )
        finally:
            if owns_client:
                await client.aclose()
        return results
