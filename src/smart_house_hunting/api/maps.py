from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from smart_house_hunting.config.loader import load_config
from smart_house_hunting.db.models import (
    NearbyAnalysisRun,
    NearbySearchCache,
    Place,
    Property,
    PropertyWalkingRoute,
)
from smart_house_hunting.maps.google import CATEGORY_TYPES, GoogleMapsClient, configured_key

router = APIRouter(prefix="/api/maps", tags=["maps"])


class NearbyRequest(BaseModel):
    property_ids: list[int] = Field(min_length=1, max_length=25)
    categories: list[
        Literal["parks", "groceries", "shopping", "cafes_restaurants", "pharmacies"]
    ] = Field(default_factory=lambda: list(CATEGORY_TYPES))
    force_refresh: bool = False
    confirm_google: bool = False


def _serialize(session, property_ids: list[int]) -> list[dict]:
    rows = session.execute(
        select(PropertyWalkingRoute, Place, Property)
        .join(Place, Place.id == PropertyWalkingRoute.place_id)
        .join(Property, Property.id == PropertyWalkingRoute.property_id)
        .where(PropertyWalkingRoute.property_id.in_(property_ids))
        .order_by(
            PropertyWalkingRoute.property_id,
            PropertyWalkingRoute.category,
            PropertyWalkingRoute.duration_seconds,
        )
    ).all()
    return [
        {
            "property_id": route.property_id,
            "property_address": f"{prop.street_address}, {prop.municipality}",
            "category": route.category,
            "name": place.name,
            "primary_type": place.primary_type,
            "formatted_address": place.formatted_address,
            "latitude": str(place.latitude),
            "longitude": str(place.longitude),
            "google_maps_uri": place.google_maps_uri,
            "walking_distance_meters": route.distance_meters,
            "walking_duration_seconds": route.duration_seconds,
            "route_status": route.route_status,
            "retrieved_at": route.retrieved_at.isoformat(),
        }
        for route, place, prop in rows
    ]


@router.get("/browser-config")
async def browser_config(request: Request) -> dict:
    config = load_config(request.app.state.config_path).maps
    key = configured_key(config, "browser") if config.enabled else None
    return {"enabled": config.enabled, "available": bool(key), "api_key": key}


@router.get("/nearby")
async def nearby_results(request: Request, property_ids: str) -> dict:
    ids = list(dict.fromkeys(int(value) for value in property_ids.split(",") if value.strip()))[:25]
    with request.app.state.session_factory() as session:
        return {"results": _serialize(session, ids)}


@router.post("/nearby-analyses")
async def analyze_nearby(body: NearbyRequest, request: Request) -> dict:
    config = load_config(request.app.state.config_path).maps
    if not config.enabled:
        raise HTTPException(409, "Google Maps is disabled in local configuration")
    key = configured_key(config, "backend")
    if not key:
        raise HTTPException(409, "The configured backend Maps key environment variable is missing")
    now = datetime.now(UTC)
    cutoff = now.replace(tzinfo=None) - timedelta(days=config.cache_days)
    ids = list(dict.fromkeys(body.property_ids))
    with request.app.state.session_factory.begin() as session:
        properties = session.scalars(select(Property).where(Property.id.in_(ids))).all()
        if len(properties) != len(ids):
            raise HTTPException(404, "One or more selected properties do not exist")
        missing_coordinates = [
            p.id for p in properties if p.latitude is None or p.longitude is None
        ]
        cached = {
            (row.property_id, row.category)
            for row in session.scalars(
                select(NearbySearchCache).where(
                    NearbySearchCache.property_id.in_(ids),
                    NearbySearchCache.category.in_(body.categories),
                    NearbySearchCache.status == "success",
                    NearbySearchCache.retrieved_at >= cutoff,
                )
            )
        }
        uncached = [
            (p, category)
            for p in properties
            for category in body.categories
            if body.force_refresh or (p.id, category) not in cached
        ]
        if uncached and not body.confirm_google:
            raise HTTPException(
                409,
                detail={
                    "code": "google_confirmation_required",
                    "message": (
                        "This sends coordinates for "
                        f"{len({p.id for p, _ in uncached})} selected properties across "
                        f"{len(body.categories)} categories to Google."
                    ),
                },
            )
        run = NearbyAnalysisRun(
            status="running",
            property_ids=ids,
            categories=list(body.categories),
            force=body.force_refresh,
            counters={},
        )
        session.add(run)
        session.flush()
        run_id = run.id

    factory = getattr(request.app.state, "maps_client_factory", None)
    client = factory(key) if factory else GoogleMapsClient(key)
    successes = failures = routes_failed = 0
    errors: list[str] = []
    try:
        for prop, category in uncached:
            if prop.id in missing_coordinates:
                failures += 1
                errors.append(f"property {prop.id}: coordinates unavailable")
                continue
            try:
                places = await client.nearby(
                    float(prop.latitude),
                    float(prop.longitude),
                    category,
                    config.nearby_search_radius_meters,
                )
                with request.app.state.session_factory.begin() as session:
                    session.execute(
                        delete(PropertyWalkingRoute).where(
                            PropertyWalkingRoute.property_id == prop.id,
                            PropertyWalkingRoute.category == category,
                        )
                    )
                    for item in places:
                        place = session.scalar(
                            select(Place).where(Place.google_place_id == item.place_id)
                        )
                        if place is None:
                            place = Place(
                                google_place_id=item.place_id,
                                name=item.name,
                                primary_type=item.primary_type,
                                types=item.types,
                                formatted_address=item.address,
                                latitude=item.latitude,
                                longitude=item.longitude,
                                google_maps_uri=item.maps_uri,
                                retrieved_at=now,
                            )
                            session.add(place)
                            session.flush()
                        else:
                            place.name, place.primary_type, place.types, place.formatted_address = (
                                item.name,
                                item.primary_type,
                                item.types,
                                item.address,
                            )
                            (
                                place.latitude,
                                place.longitude,
                                place.google_maps_uri,
                                place.retrieved_at,
                            ) = item.latitude, item.longitude, item.maps_uri, now
                        try:
                            distance, duration = await client.walking(
                                (float(prop.latitude), float(prop.longitude)),
                                (item.latitude, item.longitude),
                            )
                            route_status, route_error = "success", None
                        except Exception as error:
                            distance = duration = None
                            route_status = "failed"
                            route_error = str(error)[:500]
                            routes_failed += 1
                        session.add(
                            PropertyWalkingRoute(
                                property_id=prop.id,
                                place_id=place.id,
                                category=category,
                                distance_meters=distance,
                                duration_seconds=duration,
                                route_status=route_status,
                                error_summary=route_error,
                                retrieved_at=now,
                            )
                        )
                    cache = session.scalar(
                        select(NearbySearchCache).where(
                            NearbySearchCache.property_id == prop.id,
                            NearbySearchCache.category == category,
                        )
                    )
                    if cache is None:
                        cache = NearbySearchCache(
                            property_id=prop.id,
                            category=category,
                            status="success",
                            retrieved_at=now,
                        )
                        session.add(cache)
                    cache.status, cache.error_summary, cache.retrieved_at = "success", None, now
                successes += 1
            except Exception as error:
                failures += 1
                errors.append(f"property {prop.id}/{category}: {error}"[:500])
                with request.app.state.session_factory.begin() as session:
                    cache = session.scalar(
                        select(NearbySearchCache).where(
                            NearbySearchCache.property_id == prop.id,
                            NearbySearchCache.category == category,
                        )
                    )
                    if cache is None:
                        cache = NearbySearchCache(
                            property_id=prop.id,
                            category=category,
                            status="failed",
                            retrieved_at=now,
                        )
                        session.add(cache)
                    cache.status, cache.error_summary, cache.retrieved_at = (
                        "failed",
                        str(error)[:500],
                        now,
                    )
    finally:
        close = getattr(client, "close", None)
        if close:
            await close()
    status = "success" if failures == 0 else ("partial_success" if successes else "failed")
    with request.app.state.session_factory.begin() as session:
        run = session.get(NearbyAnalysisRun, run_id)
        run.status, run.completed_at = status, now
        run.counters = {
            "cached": len(cached),
            "searched": len(uncached),
            "successful_categories": successes,
            "failed_categories": failures,
            "failed_routes": routes_failed,
        }
        run.error_summary = "; ".join(errors)[:2000] or None
        results = _serialize(session, ids)
    return {
        "run_id": run_id,
        "status": status,
        "counters": run.counters,
        "errors": errors,
        "results": results,
    }
