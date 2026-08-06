from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from smart_house_hunting.config.models import ApplicationConfig
from smart_house_hunting.db.models import (
    Listing,
    ListingState,
    Property,
    PropertyDuplicateCandidate,
)
from smart_house_hunting.finance.calculator import (
    FinancialCalculationError,
    calculate_financials,
)
from smart_house_hunting.finance.models import FinancialCalculationRequest
from smart_house_hunting.profile.models import ProfileFinance
from smart_house_hunting.properties.models import (
    PropertyListResponse,
    PropertySourceView,
    PropertyView,
    ResolvedFact,
    SourceValue,
)

RESOLUTION_RULE = "source priority: Redfin, Zillow, then others"
SOURCE_PRIORITY = {"redfin": 0, "zillow": 1, "realtor": 2}
MANUAL_DECIMAL_FIELDS = {
    "price",
    "bedrooms",
    "bathrooms",
    "lot_size_sqft",
    "property_tax_annual",
    "hoa_monthly",
}
MANUAL_INTEGER_FIELDS = {"living_area_sqft", "year_built"}
MANUAL_FACT_FIELDS = (
    "price",
    "bedrooms",
    "bathrooms",
    "living_area_sqft",
    "lot_size_sqft",
    "property_tax_annual",
    "hoa_monthly",
    "status",
    "property_type",
    "year_built",
    "image_url",
)


def _source_priority(source: str) -> tuple[int, str]:
    canonical = source.removeprefix("fixture-")
    return SOURCE_PRIORITY.get(canonical, 100), source


def _string(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _image_url_from_facts(facts: dict[str, object]) -> str | None:
    values = facts.get("image_urls")
    if isinstance(values, str) and values.strip():
        return values.strip()
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    value = facts.get("image_url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _resolve(values: list[tuple[str, object | None]]) -> tuple[ResolvedFact, object | None]:
    source_values = [SourceValue(source=source, value=_string(value)) for source, value in values]
    known = [(source, value) for source, value in values if value is not None]
    if not known:
        return (
            ResolvedFact(
                display_value=None,
                source_values=source_values,
                conflict=False,
                resolution_rule=RESOLUTION_RULE,
            ),
            None,
        )
    _, selected = min(known, key=lambda item: _source_priority(item[0]))
    selected_key = _string(selected)
    distinct_values = {_string(value) for _, value in known}
    return (
        ResolvedFact(
            display_value=selected_key,
            source_values=source_values,
            conflict=len(distinct_values) > 1,
            resolution_rule=RESOLUTION_RULE,
        ),
        selected,
    )


def _latest_state(listing: Listing) -> ListingState | None:
    return max(listing.states, key=lambda state: state.id) if listing.states else None


def _manual_value(facts: dict[str, object], name: str) -> object | None:
    value = facts.get(name)
    if value in (None, ""):
        return None
    if name in MANUAL_DECIMAL_FIELDS:
        return Decimal(str(value))
    if name in MANUAL_INTEGER_FIELDS:
        return int(value)
    return str(value)


def _manual_display_values(facts: dict[str, object]) -> dict[str, str | int]:
    values: dict[str, str | int] = {}
    for name in MANUAL_FACT_FIELDS:
        value = _manual_value(facts, name)
        if isinstance(value, Decimal):
            values[name] = format(value, "f")
        elif isinstance(value, (str, int)):
            values[name] = value
    return values


def _duplicate_ids(session: Session, property_id: int) -> list[int]:
    rows = session.scalars(
        select(PropertyDuplicateCandidate).where(
            PropertyDuplicateCandidate.status == "possible",
            or_(
                PropertyDuplicateCandidate.property_low_id == property_id,
                PropertyDuplicateCandidate.property_high_id == property_id,
            ),
        )
    ).all()
    return sorted(
        row.property_high_id if row.property_low_id == property_id else row.property_low_id
        for row in rows
    )


def _compose_property(
    session: Session,
    property_record: Property,
    finance: ProfileFinance,
    config: ApplicationConfig,
) -> PropertyView:
    sources: list[PropertySourceView] = []
    states: list[tuple[str, ListingState]] = []
    for listing in sorted(property_record.listings, key=lambda item: _source_priority(item.source)):
        state = _latest_state(listing)
        if state is None or state.facts.get("record_kind") == "sold_comparable":
            continue
        states.append((listing.source, state))
        sources.append(
            PropertySourceView(
                source=listing.source,
                url=listing.url,
                status=state.status,
                price=state.price,
                bedrooms=state.bedrooms,
                bathrooms=state.bathrooms,
                living_area_sqft=state.living_area_sqft,
                lot_size_sqft=state.lot_size_sqft,
                property_tax_annual=state.property_tax_annual,
                hoa_monthly=state.hoa_monthly,
                detail_error=(
                    str(state.facts["detail_error"]) if state.facts.get("detail_error") else None
                ),
            )
        )

    manual_facts = property_record.manual_facts or {}
    missing_fields: list[str] = []
    resolved: dict[str, ResolvedFact] = {}
    selected: dict[str, object | None] = {}
    for name in (
        "price",
        "bedrooms",
        "bathrooms",
        "living_area_sqft",
        "lot_size_sqft",
        "property_tax_annual",
        "hoa_monthly",
        "status",
    ):
        crawl_values = [(source, getattr(state, name)) for source, state in states]
        has_crawled_value = any(value not in (None, "") for _, value in crawl_values)
        manual_value = _manual_value(manual_facts, name)
        if (
            not has_crawled_value
            and name not in {"hoa_monthly", "property_tax_annual"}
            and manual_value is None
        ):
            missing_fields.append(name)
        if not has_crawled_value and manual_value is not None:
            crawl_values.append(("manual", manual_value))
        resolved[name], selected[name] = _resolve(crawl_values)
    for name in ("property_type", "year_built"):
        crawl_values = [(source, state.facts.get(name)) for source, state in states]
        has_crawled_value = any(value not in (None, "") for _, value in crawl_values)
        manual_value = _manual_value(manual_facts, name)
        if not has_crawled_value and manual_value is None:
            missing_fields.append(name)
        if not has_crawled_value and manual_value is not None:
            crawl_values.append(("manual", manual_value))
        resolved[name], selected[name] = _resolve(crawl_values)
    crawled_image_url = next(
        (_image_url_from_facts(state.facts) for _, state in states),
        None,
    )
    manual_image_url = _manual_value(manual_facts, "image_url")
    if crawled_image_url is None and manual_image_url is None:
        missing_fields.append("image_url")
    image_url = crawled_image_url or manual_image_url

    financials = None
    financial_error = None
    if isinstance(selected["price"], Decimal):
        try:
            financials = calculate_financials(
                FinancialCalculationRequest.model_validate(
                    {
                        "finance": finance,
                        "property": {
                            "listing_price": selected["price"],
                            "annual_property_tax": selected["property_tax_annual"],
                            "monthly_hoa": selected["hoa_monthly"],
                        },
                    }
                ),
                config.finance,
            )
        except FinancialCalculationError as error:
            financial_error = str(error)

    return PropertyView(
        id=property_record.id,
        street_address=property_record.street_address,
        unit_number=property_record.unit_number,
        municipality=property_record.municipality,
        state=property_record.state,
        postal_code=property_record.postal_code,
        latitude=property_record.latitude,
        longitude=property_record.longitude,
        image_url=image_url,
        manual_tags=property_record.manual_tags,
        manual_tag_categories={
            tag: property_record.manual_tag_categories.get(tag, "bad")
            for tag in property_record.manual_tags
        },
        manual_values=_manual_display_values(manual_facts),
        retrieval_status=("retrieved" if not missing_fields else "partially_retrieved"),
        missing_fields=missing_fields,
        price=resolved["price"],
        bedrooms=resolved["bedrooms"],
        bathrooms=resolved["bathrooms"],
        living_area_sqft=resolved["living_area_sqft"],
        lot_size_sqft=resolved["lot_size_sqft"],
        property_tax_annual=resolved["property_tax_annual"],
        hoa_monthly=resolved["hoa_monthly"],
        status=resolved["status"],
        property_type=resolved["property_type"],
        year_built=resolved["year_built"],
        sources=sources,
        conflict_fields=[name for name, fact in resolved.items() if fact.conflict],
        possible_duplicate_ids=_duplicate_ids(session, property_record.id),
        financials=financials,
        financial_error=financial_error,
    )


def list_properties(
    session: Session,
    *,
    config: ApplicationConfig,
    finance: ProfileFinance,
    municipality: str | None = None,
    max_price: Decimal | None = None,
    min_bedrooms: Decimal | None = None,
    min_bathrooms: Decimal | None = None,
    built_after: int | None = None,
    sort: str = "price_asc",
) -> PropertyListResponse:
    records = session.scalars(
        select(Property)
        .options(selectinload(Property.listings).selectinload(Listing.states))
        .where(Property.municipality.in_(config.search.municipalities))
    ).all()
    records = [
        record
        for record in records
        if any(
            (state := _latest_state(listing)) is not None
            and state.facts.get("record_kind") != "sold_comparable"
            for listing in record.listings
        )
    ]
    properties = [_compose_property(session, record, finance, config) for record in records]
    properties = [
        item
        for item in properties
        if item.property_type.display_value in config.search.included_property_types
    ]
    properties = [
        item
        for item in properties
        if (
            item.price.display_value is None and any(source.detail_error for source in item.sources)
        )
        or (
            item.price.display_value is not None
            and Decimal(item.price.display_value) <= config.search.maximum_price
        )
    ]
    properties = [
        item
        for item in properties
        if item.bedrooms.display_value is not None
        and Decimal(item.bedrooms.display_value) >= config.search.minimum_bedrooms
        and item.bathrooms.display_value is not None
        and Decimal(item.bathrooms.display_value) >= config.search.minimum_bathrooms
    ]
    if municipality:
        properties = [
            item for item in properties if item.municipality.casefold() == municipality.casefold()
        ]
    if max_price is not None:
        effective_max_price = min(max_price, config.search.maximum_price)
        properties = [
            item
            for item in properties
            if (
                item.price.display_value is None
                and any(source.detail_error for source in item.sources)
            )
            or (
                item.price.display_value is not None
                and Decimal(item.price.display_value) <= effective_max_price
            )
        ]
    if min_bedrooms is not None:
        properties = [
            item
            for item in properties
            if item.bedrooms.display_value is not None
            and Decimal(item.bedrooms.display_value) >= min_bedrooms
        ]
    if min_bathrooms is not None:
        properties = [
            item
            for item in properties
            if item.bathrooms.display_value is not None
            and Decimal(item.bathrooms.display_value) >= min_bathrooms
        ]
    if built_after is not None:
        properties = [
            item
            for item in properties
            if item.year_built.display_value is not None
            and Decimal(item.year_built.display_value) > built_after
        ]
    if sort == "price_desc":
        properties.sort(key=lambda item: Decimal(item.price.display_value or "-1"), reverse=True)
    elif sort == "town":
        properties.sort(
            key=lambda item: (item.municipality.casefold(), item.street_address.casefold())
        )
    else:
        properties.sort(key=lambda item: Decimal(item.price.display_value or "Infinity"))
    return PropertyListResponse(properties=properties, count=len(properties))


def get_property(
    session: Session,
    *,
    property_id: int,
    config: ApplicationConfig,
    finance: ProfileFinance,
) -> PropertyView | None:
    record = session.scalar(
        select(Property)
        .options(selectinload(Property.listings).selectinload(Listing.states))
        .where(Property.id == property_id)
    )
    return _compose_property(session, record, finance, config) if record else None
