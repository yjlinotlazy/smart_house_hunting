from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerConfig(StrictModel):
    host: str = "localhost"
    port: int = Field(default=7004, ge=1, le=65535)


class SearchConfig(StrictModel):
    state: Literal["MA"] = "MA"
    municipalities: list[str] = Field(default_factory=list)
    included_property_types: list[
        Literal[
            "single_family",
            "condo",
            "townhouse",
            "multi_family",
            "land",
            "mobile",
            "other",
        ]
    ] = Field(default_factory=lambda: ["single_family"], min_length=1)
    minimum_bedrooms: Decimal = Field(default=Decimal(0), ge=0)
    minimum_bathrooms: Decimal = Field(default=Decimal(0), ge=0)
    maximum_price: Decimal = Field(gt=0)

    @model_validator(mode="before")
    @classmethod
    def discard_removed_recent_confirmation(cls, value: object) -> object:
        if isinstance(value, dict) and "recent_scan_confirmation_minutes" in value:
            value = dict(value)
            value.pop("recent_scan_confirmation_minutes", None)
        return value

    @field_validator("municipalities")
    @classmethod
    def normalize_municipalities(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = " ".join(raw.strip().split())
            if not value:
                continue
            key = value.casefold()
            if key not in seen:
                normalized.append(value)
                seen.add(key)
        return normalized

    @field_validator("included_property_types")
    @classmethod
    def deduplicate_property_types(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class RateRange(StrictModel):
    low: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)

    @field_validator("high")
    @classmethod
    def high_must_not_be_below_low(cls, value: Decimal, info) -> Decimal:
        low = info.data.get("low")
        if low is not None and value < low:
            raise ValueError("high must be greater than or equal to low")
        return value


class FinanceAssumptions(StrictModel):
    mortgage_years: Literal[30] = 30
    default_down_payment_percent: Decimal = Field(default=Decimal(20), ge=0, le=100)
    annual_interest_rate: RateRange
    annual_insurance_rate: RateRange
    annual_maintenance_rate: RateRange
    closing_cost_rate: RateRange


class SourceConfig(StrictModel):
    enabled: bool = True


class SourcesConfig(StrictModel):
    redfin: SourceConfig = Field(default_factory=SourceConfig)
    zillow: SourceConfig = Field(default_factory=SourceConfig)
    realtor: SourceConfig = Field(default_factory=SourceConfig)


class LLMProviderConfig(StrictModel):
    base_url: str
    api_key_env: str
    model: str


class LLMConfig(StrictModel):
    default_provider: str = "google"
    timeout_seconds: int = Field(default=180, ge=1)
    max_concurrency: int = Field(default=2, ge=1, le=20)
    providers: dict[str, LLMProviderConfig]

    @field_validator("providers")
    @classmethod
    def providers_must_include_google(
        cls, providers: dict[str, LLMProviderConfig]
    ) -> dict[str, LLMProviderConfig]:
        if "google" not in providers:
            raise ValueError("google provider is required")
        return providers


class LoggingConfig(StrictModel):
    level: str = "INFO"
    include_profile_content: Literal[False] = False
    retain_source_payloads: bool = True


class MapsConfig(StrictModel):
    enabled: bool = False
    demo_api_key_env: str | None = "GOOGLE_MAPS_API_KEY"
    browser_api_key_env: str = "GOOGLE_MAPS_BROWSER_API_KEY"
    backend_api_key_env: str = "GOOGLE_MAPS_BACKEND_API_KEY"
    nearby_search_radius_meters: int = Field(default=2500, ge=100, le=50000)
    cache_days: int = Field(default=14, ge=1, le=90)


class ApplicationConfig(StrictModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    profile_file: Path
    search: SearchConfig
    finance: FinanceAssumptions
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    llm: LLMConfig
    maps: MapsConfig = Field(default_factory=MapsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class PublicServerConfig(StrictModel):
    host: str
    port: int


class PublicLLMConfig(StrictModel):
    default_provider: str
    providers: list[str]


class PublicApplicationConfig(StrictModel):
    server: PublicServerConfig
    search: SearchConfig
    llm: PublicLLMConfig


class ConfigUpdate(StrictModel):
    municipalities: list[str]


class ConfigText(StrictModel):
    content: str = Field(max_length=1_000_000)


def to_public_config(config: ApplicationConfig) -> PublicApplicationConfig:
    return PublicApplicationConfig(
        server=PublicServerConfig(host=config.server.host, port=config.server.port),
        search=config.search,
        llm=PublicLLMConfig(
            default_provider=config.llm.default_provider,
            providers=sorted(config.llm.providers),
        ),
    )
