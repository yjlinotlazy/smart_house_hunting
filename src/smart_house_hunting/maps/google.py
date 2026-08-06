from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import httpx

from smart_house_hunting.config.models import MapsConfig

CATEGORY_TYPES = {
    "parks": ["park"],
    "groceries": ["grocery_store", "supermarket"],
    "shopping": ["store", "shopping_mall"],
    "cafes_restaurants": ["cafe", "restaurant"],
    "pharmacies": ["pharmacy"],
}


@dataclass(frozen=True)
class NearbyPlace:
    place_id: str
    name: str
    primary_type: str | None
    types: list[str]
    address: str | None
    latitude: float
    longitude: float
    maps_uri: str | None


class PlacesProvider(Protocol):
    async def nearby(
        self, latitude: float, longitude: float, category: str, radius: int
    ) -> list[NearbyPlace]: ...


class RoutesProvider(Protocol):
    async def walking(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> tuple[int, int]: ...


def configured_key(config: MapsConfig, purpose: str) -> str | None:
    specific = config.browser_api_key_env if purpose == "browser" else config.backend_api_key_env
    if value := os.environ.get(specific):
        return value
    if config.demo_api_key_env:
        return os.environ.get(config.demo_api_key_env)
    return None


class GoogleMapsClient:
    def __init__(self, api_key: str, timeout: float = 15) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def nearby(
        self, latitude: float, longitude: float, category: str, radius: int
    ) -> list[NearbyPlace]:
        included = CATEGORY_TYPES[category]
        response = await self._client.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers={
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": (
                    "places.id,places.displayName,places.formattedAddress,places.location,"
                    "places.primaryType,places.types,places.googleMapsUri"
                ),
            },
            json={
                "includedTypes": included,
                "maxResultCount": 5,
                "rankPreference": "DISTANCE",
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": radius,
                    }
                },
            },
        )
        response.raise_for_status()
        deduped: dict[str, NearbyPlace] = {}
        for raw in response.json().get("places", []):
            location = raw.get("location") or {}
            place_id = raw.get("id")
            if not place_id or "latitude" not in location or "longitude" not in location:
                continue
            deduped[place_id] = NearbyPlace(
                place_id=place_id,
                name=(raw.get("displayName") or {}).get("text") or "Unnamed place",
                primary_type=raw.get("primaryType"),
                types=raw.get("types") or [],
                address=raw.get("formattedAddress"),
                latitude=location["latitude"],
                longitude=location["longitude"],
                maps_uri=raw.get("googleMapsUri"),
            )
        return list(deduped.values())

    async def walking(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> tuple[int, int]:
        response = await self._client.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers={
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
            },
            json={
                "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
                "destination": {
                    "location": {
                        "latLng": {"latitude": destination[0], "longitude": destination[1]}
                    }
                },
                "travelMode": "WALK",
                "computeAlternativeRoutes": False,
                "units": "IMPERIAL",
            },
        )
        response.raise_for_status()
        routes = response.json().get("routes") or []
        if not routes:
            raise ValueError("Google returned no walking route")
        route = routes[0]
        return int(route["distanceMeters"]), int(float(str(route["duration"]).removesuffix("s")))
