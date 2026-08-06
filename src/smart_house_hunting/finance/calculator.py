from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from smart_house_hunting.config.models import FinanceAssumptions, RateRange
from smart_house_hunting.finance.models import (
    DecimalRange,
    DownPaymentResult,
    FinancialCalculationRequest,
    FinancialCalculationResult,
    IncomeImpact,
)

MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
MONTHS_PER_YEAR = Decimal(12)


class FinancialCalculationError(ValueError):
    """Raised when inputs are individually valid but cannot form a mortgage."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT, rounding=ROUND_HALF_UP)


def _money_range(low: Decimal, high: Decimal) -> DecimalRange:
    return DecimalRange(low=_money(low), high=_money(high))


def _rate_range(amount: Decimal, rates: RateRange, divisor: Decimal = Decimal(1)) -> DecimalRange:
    return _money_range(amount * rates.low / divisor, amount * rates.high / divisor)


def _monthly_payment(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    if principal == 0:
        return Decimal(0)
    if annual_rate == 0:
        return principal / Decimal(months)
    monthly_rate = annual_rate / MONTHS_PER_YEAR
    factor = (Decimal(1) + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - Decimal(1))


def _income_impact(
    annual_income: Decimal,
    annual_travel: Decimal,
    housing: DecimalRange,
) -> IncomeImpact:
    monthly_income = annual_income / MONTHS_PER_YEAR
    monthly_travel = annual_travel / MONTHS_PER_YEAR
    ratio = None
    if monthly_income > 0:
        ratio = DecimalRange(
            low=_percent(housing.low / monthly_income * Decimal(100)),
            high=_percent(housing.high / monthly_income * Decimal(100)),
        )
    return IncomeImpact(
        housing_percent=ratio,
        monthly_gross_balance_after_housing_and_travel=DecimalRange(
            low=_money(monthly_income - monthly_travel - housing.high),
            high=_money(monthly_income - monthly_travel - housing.low),
        ),
    )


def calculate_financials(
    request: FinancialCalculationRequest,
    assumptions: FinanceAssumptions,
) -> FinancialCalculationResult:
    price = request.property.listing_price
    planned = request.finance.down_payment
    if planned.mode == "amount":
        down_amount = planned.value
        down_percent = down_amount / price * Decimal(100)
    else:
        down_percent = planned.value
        down_amount = price * down_percent / Decimal(100)

    if down_amount > price or down_percent > Decimal(100):
        raise FinancialCalculationError("Down payment cannot exceed the listing price")

    down_amount = _money(down_amount)
    down_percent = _percent(down_percent)
    loan = _money(price - down_amount)
    months = assumptions.mortgage_years * 12
    principal_interest = _money_range(
        _monthly_payment(loan, assumptions.annual_interest_rate.low, months),
        _monthly_payment(loan, assumptions.annual_interest_rate.high, months),
    )
    insurance = _rate_range(price, assumptions.annual_insurance_rate, MONTHS_PER_YEAR)
    maintenance = _rate_range(price, assumptions.annual_maintenance_rate, MONTHS_PER_YEAR)
    closing = _rate_range(price, assumptions.closing_cost_rate)

    tax = request.property.annual_property_tax
    monthly_tax = _money(tax / MONTHS_PER_YEAR) if tax is not None else None
    hoa = request.property.monthly_hoa
    monthly_hoa = _money(hoa) if hoa is not None else None
    exact_monthly = (monthly_tax or Decimal(0)) + (monthly_hoa or Decimal(0))
    known_subtotal = _money_range(
        principal_interest.low + exact_monthly,
        principal_interest.high + exact_monthly,
    )
    total = _money_range(
        known_subtotal.low + insurance.low + maintenance.low,
        known_subtotal.high + insurance.high + maintenance.high,
    )
    unknown: list[str] = []
    if tax is None:
        unknown.append("property_tax")
    if hoa is None:
        unknown.append("hoa")

    return FinancialCalculationResult(
        listing_price=_money(price),
        down_payment=DownPaymentResult(
            authoritative_mode=planned.mode,
            amount=down_amount,
            percent=down_percent,
        ),
        loan_amount=loan,
        estimated_closing_cost=closing,
        monthly_principal_and_interest=principal_interest,
        monthly_property_tax=monthly_tax,
        monthly_insurance=insurance,
        monthly_hoa=monthly_hoa,
        monthly_maintenance=maintenance,
        known_monthly_housing_subtotal=known_subtotal,
        estimated_monthly_housing_total=total,
        total_is_partial=bool(unknown),
        unknown_components=unknown,
        current_income=_income_impact(
            request.finance.current_annual_gross_income,
            request.finance.annual_travel_spending,
            total,
        ),
        minimum_future_income=_income_impact(
            request.finance.minimum_future_annual_gross_income,
            request.finance.annual_travel_spending,
            total,
        ),
    )
