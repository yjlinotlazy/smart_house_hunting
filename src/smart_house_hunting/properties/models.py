from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from smart_house_hunting.finance.models import FinancialCalculationResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualTagsUpdate(StrictModel):
    tags: list[str] = Field(max_length=50)
    categories: dict[str, Literal["good", "bad", "neutral"]] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = " ".join(raw.strip().split())
            if not value:
                raise ValueError("tags cannot be empty")
            if len(value) > 50:
                raise ValueError("tags cannot exceed 50 characters")
            key = value.casefold()
            if key not in seen:
                normalized.append(value)
                seen.add(key)
        return normalized


class ManualFactsUpdate(StrictModel):
    price: Decimal | None = Field(default=None, ge=0)
    bedrooms: Decimal | None = Field(default=None, ge=0)
    bathrooms: Decimal | None = Field(default=None, ge=0)
    living_area_sqft: int | None = Field(default=None, ge=0)
    lot_size_sqft: Decimal | None = Field(default=None, ge=0)
    lot_size_acres: Decimal | None = Field(default=None, ge=0)
    property_tax_annual: Decimal | None = Field(default=None, ge=0)
    hoa_monthly: Decimal | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=50)
    property_type: str | None = Field(default=None, max_length=50)
    year_built: int | None = Field(default=None, ge=1000, le=2100)
    image_url: str | None = Field(default=None, max_length=2000)

    @field_validator("status", "property_type", "image_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SourceValue(StrictModel):
    source: str
    value: str | None


class ResolvedFact(StrictModel):
    display_value: str | None
    source_values: list[SourceValue]
    conflict: bool
    resolution_rule: str


class PropertySourceView(StrictModel):
    source: str
    url: str
    status: str | None
    price: Decimal | None
    bedrooms: Decimal | None
    bathrooms: Decimal | None
    living_area_sqft: int | None
    lot_size_sqft: Decimal | None
    property_tax_annual: Decimal | None
    hoa_monthly: Decimal | None
    detail_error: str | None = None


class PropertyView(StrictModel):
    id: int
    street_address: str
    unit_number: str | None
    municipality: str
    state: str
    postal_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    image_url: str | None
    manual_tags: list[str]
    manual_tag_categories: dict[str, Literal["good", "bad", "neutral"]]
    manual_values: dict[str, str | int]
    retrieval_status: Literal["retrieved", "partially_retrieved"]
    missing_fields: list[str]
    price: ResolvedFact
    bedrooms: ResolvedFact
    bathrooms: ResolvedFact
    living_area_sqft: ResolvedFact
    lot_size_sqft: ResolvedFact
    property_tax_annual: ResolvedFact
    hoa_monthly: ResolvedFact
    status: ResolvedFact
    property_type: ResolvedFact
    year_built: ResolvedFact
    sources: list[PropertySourceView]
    conflict_fields: list[str]
    possible_duplicate_ids: list[int]
    financials: FinancialCalculationResult | None
    financial_error: str | None


class PropertyListResponse(StrictModel):
    properties: list[PropertyView]
    count: int


class PropertyEventView(StrictModel):
    id: int
    event_type: str
    source: str | None
    source_url: str | None
    occurred_at: datetime
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


class PropertyHistoryResponse(StrictModel):
    property_id: int
    events: list[PropertyEventView]


class SoldComparableView(StrictModel):
    id: int
    source: str
    url: str
    street_address: str | None
    municipality: str | None
    sale_date: date | None
    sale_price: Decimal | None
    original_listing_price: Decimal | None
    final_listing_price: Decimal | None
    difference_from_original: Decimal | None
    difference_from_final: Decimal | None
    property_type: str | None
    bedrooms: Decimal | None
    bathrooms: Decimal | None
    living_area_sqft: int | None
    distance_miles: Decimal | None
    similarity_score: int
    similarity_reasons: list[str]
    scope: str
    retrieved_at: datetime
    missing_fields: list[str]


class SoldComparableResponse(StrictModel):
    property_id: int
    comparables: list[SoldComparableView]
    expanded_to_nearby_towns: bool
    disclaimer: str = "Historical comparable sales only; this is not a price prediction."
