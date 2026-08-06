from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DownPayment(StrictModel):
    mode: Literal["amount", "percent"] = "amount"
    value: Decimal = Field(default=Decimal(0), ge=0)


class ProfileFinance(StrictModel):
    current_annual_gross_income: Decimal = Field(default=Decimal(0), ge=0)
    minimum_future_annual_gross_income: Decimal = Field(default=Decimal(0), ge=0)
    annual_travel_spending: Decimal = Field(default=Decimal(0), ge=0)
    down_payment: DownPayment = Field(default_factory=DownPayment)


class HouseholdProfile(StrictModel):
    family: str = ""
    must_have: str = ""
    good_to_have: str = ""
    finance: ProfileFinance = Field(default_factory=ProfileFinance)


class ProfileReadResponse(StrictModel):
    profile: HouseholdProfile
    exists: bool
    version: str


class ProfileSaveResponse(ProfileReadResponse):
    backup_created: bool
