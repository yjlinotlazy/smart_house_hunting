from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from smart_house_hunting.profile.models import ProfileFinance


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyFinancialInputs(StrictModel):
    listing_price: Decimal = Field(gt=0)
    annual_property_tax: Decimal | None = Field(default=None, ge=0)
    monthly_hoa: Decimal | None = Field(default=None, ge=0)


class FinancialCalculationRequest(StrictModel):
    finance: ProfileFinance
    property: PropertyFinancialInputs


class DecimalRange(StrictModel):
    low: Decimal
    high: Decimal


class DownPaymentResult(StrictModel):
    authoritative_mode: str
    amount: Decimal
    percent: Decimal


class IncomeImpact(StrictModel):
    housing_percent: DecimalRange | None
    monthly_gross_balance_after_housing_and_travel: DecimalRange


class FinancialCalculationResult(StrictModel):
    listing_price: Decimal
    down_payment: DownPaymentResult
    loan_amount: Decimal
    estimated_closing_cost: DecimalRange
    monthly_principal_and_interest: DecimalRange
    monthly_property_tax: Decimal | None
    monthly_insurance: DecimalRange
    monthly_hoa: Decimal | None
    monthly_maintenance: DecimalRange
    known_monthly_housing_subtotal: DecimalRange
    estimated_monthly_housing_total: DecimalRange
    total_is_partial: bool
    unknown_components: list[str]
    current_income: IncomeImpact
    minimum_future_income: IncomeImpact
