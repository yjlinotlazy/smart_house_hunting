from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
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

REALTOR_ROOT = "https://www.realtor.com"
PROPERTY_TYPE_FILTERS = {
    "single_family": "single-family-home",
    "condo": "condo",
    "townhouse": "townhome",
    "multi_family": "multi-family-home",
    "land": "land",
    "mobile": "mfd-mobile-home",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_LISTING_ID = re.compile(r"_([A-Z]\d+(?:-\d+)*)/?(?:[?#].*)?$")
_PRICE = re.compile(r"\$([\d,]+(?:\.\d+)?)")
_BED_BATH = re.compile(
    r"(?P<beds>\d+(?:\.\d+)?)\s*bed,\s*(?P<baths>\d+(?:\.\d+)?)\s*bath",
    re.I,
)
_ZERO_RESULTS = re.compile(r"\b0\s+(?:homes?|results?|properties)\b", re.I)
logger = logging.getLogger(__name__)


class RealtorError(RuntimeError):
    """Base class for sanitized Realtor source failures."""


class RealtorConfigurationError(RealtorError):
    pass


class RealtorAccessBlocked(RealtorError):
    pass


class RealtorLayoutError(RealtorError):
    pass


class RealtorRequestError(RealtorError):
    pass


class RealtorListingUnavailable(RealtorError):
    pass


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._buffer: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and (
            attributes.get("type") == "application/ld+json"
            or attributes.get("id") == "__NEXT_DATA__"
        ):
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


class _PropertyCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current: dict[str, Any] | None = None
        self._div_depth = 0
        self._meta: str | None = None
        self.cards: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._current is None:
            if tag == "div" and attributes.get("data-testid") == "property-card":
                self._current = {"text": [], "meta": {}}
                self._div_depth = 1
            return
        if tag == "div":
            self._div_depth += 1
        if tag == "a" and attributes.get("data-card-link") == "true":
            if not self._current.get("href"):
                self._current["href"] = attributes.get("href")
                self._current["aria_label"] = attributes.get("aria-label")
        elif tag == "li" and str(attributes.get("data-testid", "")).startswith("property-meta-"):
            self._meta = str(attributes["data-testid"]).removeprefix("property-meta-")
            self._current["meta"][self._meta] = []
        elif tag == "img" and not self._current.get("image_url"):
            self._current["image_url"] = attributes.get("src")

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = data.strip()
        if not text:
            return
        self._current["text"].append(text)
        if self._meta is not None:
            self._current["meta"][self._meta].append(text)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "li":
            self._meta = None
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
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
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _decimal(value)
    return int(number) if number is not None and number >= 0 else None


def _schema_type(node: dict[str, Any], expected: str) -> bool:
    value = node.get("@type")
    return value == expected or isinstance(value, list) and expected in value


def _compact_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _town_slug(municipality: str, state: str) -> str:
    town = re.sub(r"[^A-Za-z0-9]+", "-", municipality).strip("-")
    return f"{town}_{state.upper()}"


def build_search_url(request: ScanRequest, municipality: str) -> str:
    unsupported = set(request.included_property_types) - set(PROPERTY_TYPE_FILTERS)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise RealtorConfigurationError(f"Realtor property filters are unsupported: {names}")
    types = ",".join(PROPERTY_TYPE_FILTERS[item] for item in request.included_property_types)
    segments = [
        f"{REALTOR_ROOT}/realestateandhomes-search/{_town_slug(municipality, request.state)}",
        f"type-{types}",
    ]
    if request.minimum_bedrooms:
        segments.append(f"beds-{_compact_decimal(request.minimum_bedrooms)}")
    if request.minimum_bathrooms:
        segments.append(f"baths-{_compact_decimal(request.minimum_bathrooms)}")
    segments.append(f"price-na-{_compact_decimal(request.maximum_price)}")
    return "/".join(segments)


def build_sold_search_url(request: ScanRequest, municipality: str) -> str:
    unsupported = set(request.included_property_types) - set(PROPERTY_TYPE_FILTERS)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise RealtorConfigurationError(f"Realtor property filters are unsupported: {names}")
    types = ",".join(PROPERTY_TYPE_FILTERS[item] for item in request.included_property_types)
    segments = [
        f"{REALTOR_ROOT}/realestateandhomes-search/{_town_slug(municipality, request.state)}",
        "show-recently-sold",
        f"type-{types}",
    ]
    if request.minimum_bedrooms:
        segments.append(f"beds-{_compact_decimal(request.minimum_bedrooms)}")
    if request.minimum_bathrooms:
        segments.append(f"baths-{_compact_decimal(request.minimum_bathrooms)}")
    return "/".join(segments)


def _listing_id(url: str) -> str:
    match = _LISTING_ID.search(url)
    if match is None:
        raise RealtorLayoutError("Realtor listing URL does not contain a listing ID")
    return match.group(1)


def _property_type(text: str) -> str:
    normalized = text.casefold()
    if "townhome" in normalized or "townhouse" in normalized:
        return "townhouse"
    if "condo" in normalized:
        return "condo"
    if "multi-family" in normalized or "multi family" in normalized:
        return "multi_family"
    if "mobile" in normalized or "manufactured" in normalized:
        return "mobile"
    if "land for sale" in normalized or "lot for sale" in normalized:
        return "land"
    if "house for sale" in normalized or "single family" in normalized:
        return "single_family"
    return "other"


def _meta_number(card: dict[str, Any], name: str) -> Decimal | None:
    for part in card.get("meta", {}).get(name, []):
        match = re.search(r"[\d,.]+", str(part))
        if match and (number := _decimal(match.group())) is not None:
            return number
    return None


def _lot_size_sqft(card: dict[str, Any]) -> Decimal | None:
    parts = card.get("meta", {}).get("lot-size", [])
    text = " ".join(str(part) for part in parts)
    match = re.search(r"[\d,.]+", text)
    value = _decimal(match.group()) if match else None
    if value is None:
        return None
    if "acre" in text.casefold():
        return value * Decimal("43560")
    return value


def _from_card(card: dict[str, Any], municipality: str) -> NormalizedListing | None:
    href = card.get("href")
    label = card.get("aria_label")
    if not isinstance(href, str) or not isinstance(label, str):
        return None
    url = urljoin(REALTOR_ROOT, href)
    address_text = re.sub(r"^View details for\s+", "", label, flags=re.I)
    parts = [part.strip() for part in address_text.split(",")]
    if len(parts) < 3:
        return None
    state_zip = parts[-1].split()
    if not state_zip:
        return None
    text = " ".join(card.get("text", []))
    price_match = _PRICE.search(text)
    image_url = card.get("image_url")
    return NormalizedListing(
        source="realtor",
        source_listing_id=_listing_id(url),
        url=url,
        street_address=", ".join(parts[:-2]),
        municipality=parts[-2] or municipality,
        state=state_zip[0],
        postal_code=state_zip[1] if len(state_zip) > 1 else None,
        price=_decimal(price_match.group(1)) if price_match else None,
        status="active",
        bedrooms=_meta_number(card, "beds"),
        bathrooms=_meta_number(card, "baths"),
        living_area_sqft=_integer(_meta_number(card, "sqft")),
        lot_size_sqft=_lot_size_sqft(card),
        facts={
            "property_type": _property_type(text),
            "image_urls": [image_url] if image_url else [],
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
    parser = _PropertyCardParser()
    parser.feed(html)
    candidates: list[NormalizedListing] = []
    seen: set[str] = set()
    for card in parser.cards:
        candidate = _from_card(card, municipality)
        if candidate is None or candidate.source_listing_id in seen:
            continue
        if not _eligible(candidate, request, municipality):
            continue
        seen.add(candidate.source_listing_id)
        candidates.append(candidate)
    if not candidates and not _ZERO_RESULTS.search(html):
        raise RealtorLayoutError("Realtor search page contained no parseable matching listings")
    return candidates


def parse_sold_search_page(
    html: str, request: ScanRequest, municipality: str, maximum_results: int = 12
) -> list[NormalizedListing]:
    parser = _PropertyCardParser()
    parser.feed(html)
    candidates: list[NormalizedListing] = []
    seen: set[str] = set()
    assumed_type = (
        request.included_property_types[0] if len(request.included_property_types) == 1 else "other"
    )
    for card in parser.cards:
        candidate = _from_card(card, municipality)
        if candidate is None:
            continue
        text = " ".join(str(part) for part in card.get("text", []))
        if "sold" not in text.casefold():
            continue
        property_type = _property_type(text)
        if property_type == "other":
            property_type = assumed_type
        if (
            candidate.municipality.casefold() != municipality.casefold()
            or candidate.state.casefold() != request.state.casefold()
            or property_type not in request.included_property_types
            or candidate.bedrooms is None
            or candidate.bedrooms < request.minimum_bedrooms
            or candidate.bathrooms is None
            or candidate.bathrooms < request.minimum_bathrooms
        ):
            continue
        original_id = candidate.source_listing_id
        sale_price = candidate.price
        sold_id = f"{original_id}-sold-{sale_price if sale_price is not None else 'unknown'}"
        if sold_id in seen:
            continue
        seen.add(sold_id)
        candidates.append(
            candidate.model_copy(
                update={
                    "source_listing_id": sold_id,
                    "status": "sold",
                    "facts": {
                        **candidate.facts,
                        "property_type": property_type,
                        "record_kind": "sold_comparable",
                        "source_property_id": original_id,
                        "sold_history": [
                            {
                                "sale_date": None,
                                "sale_price": str(sale_price) if sale_price is not None else None,
                                "original_listing_price": None,
                                "final_listing_price": None,
                            }
                        ],
                    },
                }
            )
        )
        if len(candidates) >= maximum_results:
            break
    if not candidates and not _ZERO_RESULTS.search(html):
        raise RealtorLayoutError("Realtor sold page contained no parseable sold listings")
    return candidates


def parse_detail_page(html: str, fallback: NormalizedListing) -> NormalizedListing:
    parser = _JsonLdParser()
    parser.feed(html)
    residence: dict[str, Any] | None = None
    product: dict[str, Any] | None = None
    property_record: dict[str, Any] | None = None
    for document in parser.documents:
        for node in _walk(document):
            if not isinstance(node, dict):
                continue
            node_url = str(node.get("url", "")).rstrip("/")
            if node_url and node_url != fallback.url.rstrip("/"):
                continue
            if residence is None and _schema_type(node, "SingleFamilyResidence"):
                residence = node
            if product is None and _schema_type(node, "Product"):
                product = node
            href = str(node.get("href", "")).rstrip("/")
            if href == fallback.url.rstrip("/") and (
                node.get("last_sold_date") or node.get("last_sold_price")
            ):
                property_record = node
    if residence is None or product is None:
        raise RealtorLayoutError("Realtor detail page omitted matching structured data")
    address = residence.get("address") if isinstance(residence.get("address"), dict) else {}
    geo = residence.get("geo") if isinstance(residence.get("geo"), dict) else {}
    floor = residence.get("floorSize") if isinstance(residence.get("floorSize"), dict) else {}
    offer = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    description = str(residence.get("description") or product.get("description") or "")
    bed_bath = _BED_BATH.search(description)
    availability = str(offer.get("availability", ""))
    if availability.endswith("InStock"):
        status = "active"
    elif availability.endswith(("SoldOut", "OutOfStock")):
        status = "off_market"
    else:
        status = fallback.status
    image = residence.get("image") or product.get("image")
    image_urls = [image] if isinstance(image, str) else fallback.facts.get("image_urls", [])
    sold_history: list[dict[str, object]] = []
    year_built = None
    if property_record is not None:
        sale_date = property_record.get("last_sold_date")
        sale_price = _decimal(property_record.get("last_sold_price"))
        if sale_date or sale_price is not None:
            sold_history.append(
                {
                    "sale_date": sale_date,
                    "sale_price": str(sale_price) if sale_price is not None else None,
                    "original_listing_price": None,
                    "final_listing_price": None,
                }
            )
        for node in _walk(property_record):
            if isinstance(node, dict) and node.get("year_built") is not None:
                year_built = _integer(node.get("year_built"))
                break
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
            "bedrooms": _decimal(bed_bath.group("beds")) if bed_bath else fallback.bedrooms,
            "bathrooms": _decimal(bed_bath.group("baths")) if bed_bath else fallback.bathrooms,
            "living_area_sqft": _integer(floor.get("value")) or fallback.living_area_sqft,
            "lot_size_sqft": fallback.lot_size_sqft,
            "description": description or fallback.description,
            "facts": {
                **fallback.facts,
                "property_type": fallback.facts.get("property_type", "other"),
                "year_built": year_built or fallback.facts.get("year_built"),
                "image_urls": image_urls,
                "raw_crawled_data": property_record,
                "sold_history": sold_history or fallback.facts.get("sold_history", []),
            },
        }
    )


def _blocked(response: httpx.Response) -> bool:
    sample = response.text[:20_000].casefold()
    final_url = str(response.url).casefold()
    return (
        response.status_code in {403, 429}
        or response.headers.get("x-px-blocked") == "1"
        or "/captcha" in final_url
        or "access to this page has been denied" in sample
        or "verify you are human" in sample
    )


def _reuse_detail(current: NormalizedListing, previous: NormalizedListing) -> NormalizedListing:
    return merge_missing_listing(current, previous)


class RealtorSourceAdapter:
    name = "realtor"
    parser_version = "realtor-html-jsonld-v1"

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
            logger.info("realtor rate-limit wait seconds=%.1f", remaining)
            await self._sleep(remaining)

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        for attempt in range(self._max_attempts):
            await self._pace()
            self._last_request_at = time.monotonic()
            started_at = time.monotonic()
            path = urlparse(url).path
            logger.info(
                "realtor request started path=%s attempt=%s/%s",
                path,
                attempt + 1,
                self._max_attempts,
            )
            try:
                response = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                logger.warning(
                    "realtor request error path=%s attempt=%s error_type=%s",
                    path,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt + 1 == self._max_attempts:
                    raise RealtorRequestError(
                        "Realtor request failed after bounded retries"
                    ) from error
                await self._sleep(2**attempt)
                continue
            logger.info(
                "realtor response path=%s status=%s bytes=%s elapsed_seconds=%.2f",
                path,
                response.status_code,
                len(response.content),
                time.monotonic() - started_at,
            )
            retain_response_payload("realtor", response, enabled=self._retain_payloads)
            if _blocked(response):
                logger.error("realtor access blocked path=%s status=%s", path, response.status_code)
                raise RealtorAccessBlocked("Realtor blocked the request; scanning stopped")
            if response.status_code == 404:
                raise RealtorListingUnavailable("Realtor listing is no longer available")
            if response.status_code >= 500 and attempt + 1 < self._max_attempts:
                await self._sleep(2**attempt)
                continue
            if response.is_error:
                raise RealtorRequestError(f"Realtor returned HTTP {response.status_code}")
            return response.text
        raise RealtorRequestError("Realtor request failed")

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
                    "realtor listings discovered municipality=%s count=%s",
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
                        except RealtorAccessBlocked:
                            raise
                        except (
                            RealtorLayoutError,
                            RealtorListingUnavailable,
                            RealtorRequestError,
                        ) as error:
                            detail_failed = True
                            logger.warning(
                                "realtor detail degraded municipality=%s listing_id=%s "
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
                except RealtorListingUnavailable:
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

    async def scan_sold(
        self,
        request: ScanRequest,
        progress: ProgressCallback,
    ) -> list[NormalizedListing]:
        self._retain_payloads = request.retain_source_payloads
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(20),
        )
        results: list[NormalizedListing] = []
        try:
            for index, municipality in enumerate(request.municipalities, start=1):
                await progress(
                    "sold_search_started",
                    {
                        "municipality": municipality,
                        "current": index,
                        "total": len(request.municipalities),
                    },
                )
                html = await self._get(client, build_sold_search_url(request, municipality))
                sold = parse_sold_search_page(html, request, municipality)
                results.extend(sold)
                logger.info(
                    "realtor sold listings discovered municipality=%s count=%s",
                    municipality,
                    len(sold),
                )
                await progress(
                    "sold_search_completed",
                    {
                        "municipality": municipality,
                        "current": index,
                        "total": len(request.municipalities),
                        "count": len(sold),
                    },
                )
        finally:
            if owns_client:
                await client.aclose()
        return results
