from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from smart_house_hunting.config.loader import ConfigError, load_config
from smart_house_hunting.db.models import Property
from smart_house_hunting.profile.storage import ProfileStorageError, ProfileStore
from smart_house_hunting.properties.models import (
    ManualFactsUpdate,
    ManualTagsUpdate,
    PropertyHistoryResponse,
    PropertyListResponse,
    PropertyView,
    SoldComparableResponse,
)
from smart_house_hunting.services.comparables import property_comparables
from smart_house_hunting.services.history import property_history
from smart_house_hunting.services.properties import get_property, list_properties

router = APIRouter(prefix="/api/properties", tags=["properties"])


def _context(request: Request):
    config = load_config(request.app.state.config_path)
    profile, _, _ = ProfileStore(
        config.profile_file,
        default_down_payment_percent=config.finance.default_down_payment_percent,
    ).read()
    return config, profile.finance


@router.get("")
async def properties(
    request: Request,
    municipality: str | None = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    min_bedrooms: Annotated[Decimal | None, Query(ge=0)] = None,
    min_bathrooms: Annotated[Decimal | None, Query(ge=0)] = None,
    built_after: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[str, Query(pattern="^(price_asc|price_desc|town)$")] = "price_asc",
) -> PropertyListResponse:
    try:
        config, finance = _context(request)
        with request.app.state.session_factory() as session:
            return list_properties(
                session,
                config=config,
                finance=finance,
                municipality=municipality,
                max_price=max_price,
                min_bedrooms=min_bedrooms,
                min_bathrooms=min_bathrooms,
                built_after=built_after,
                sort=sort,
            )
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/{property_id}")
async def property_detail(property_id: int, request: Request) -> PropertyView:
    try:
        config, finance = _context(request)
        with request.app.state.session_factory() as session:
            result = get_property(session, property_id=property_id, config=config, finance=finance)
        if result is None:
            raise HTTPException(status_code=404, detail="Property not found")
        return result
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.put("/{property_id}/manual-tags")
async def update_manual_tags(
    property_id: int, body: ManualTagsUpdate, request: Request
) -> PropertyView:
    try:
        config, finance = _context(request)
        with request.app.state.session_factory.begin() as session:
            record = session.get(Property, property_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Property not found")
            record.manual_tags = body.tags
            record.manual_tag_categories = {
                tag: body.categories.get(tag, (record.manual_tag_categories or {}).get(tag, "bad"))
                for tag in body.tags
            }
            session.flush()
            result = get_property(session, property_id=property_id, config=config, finance=finance)
        return result
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.patch("/{property_id}/manual-facts")
async def update_manual_facts(
    property_id: int, body: ManualFactsUpdate, request: Request
) -> PropertyView:
    try:
        config, finance = _context(request)
        values = body.model_dump(mode="json")
        acres = values.pop("lot_size_acres", None)
        if acres is not None:
            values["lot_size_sqft"] = str(Decimal(str(acres)) * Decimal("43560"))
        with request.app.state.session_factory.begin() as session:
            record = session.get(Property, property_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Property not found")
            manual_facts = dict(record.manual_facts or {})
            for field in body.model_fields_set:
                if field == "lot_size_acres":
                    continue
                value = values[field]
                if value is None:
                    manual_facts.pop(field, None)
                else:
                    manual_facts[field] = value
            record.manual_facts = manual_facts
            session.flush()
            result = get_property(session, property_id=property_id, config=config, finance=finance)
        return result
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/{property_id}/history")
async def history(property_id: int, request: Request) -> PropertyHistoryResponse:
    with request.app.state.session_factory() as session:
        result = property_history(session, property_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return result


@router.get("/{property_id}/comparables")
async def comparables(property_id: int, request: Request) -> SoldComparableResponse:
    with request.app.state.session_factory() as session:
        result = property_comparables(session, property_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return result
