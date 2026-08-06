from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.config.models import FinanceAssumptions, RateRange
from smart_house_hunting.finance.calculator import (
    FinancialCalculationError,
    calculate_financials,
)
from smart_house_hunting.finance.models import FinancialCalculationRequest
from smart_house_hunting.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def assumptions(low: str = "0.06", high: str = "0.06") -> FinanceAssumptions:
    return FinanceAssumptions(
        mortgage_years=30,
        annual_interest_rate=RateRange(low=low, high=high),
        annual_insurance_rate=RateRange(low="0.002", high="0.004"),
        annual_maintenance_rate=RateRange(low="0.005", high="0.01"),
        closing_cost_rate=RateRange(low="0.02", high="0.05"),
    )


def calculation(
    *,
    mode: str = "amount",
    down_payment: str = "100000",
    price: str = "500000",
    tax: str | None = "6000",
    hoa: str | None = "0",
    current_income: str = "180000",
) -> FinancialCalculationRequest:
    return FinancialCalculationRequest.model_validate(
        {
            "finance": {
                "current_annual_gross_income": current_income,
                "minimum_future_annual_gross_income": "120000",
                "annual_travel_spending": "12000",
                "down_payment": {"mode": mode, "value": down_payment},
            },
            "property": {
                "listing_price": price,
                "annual_property_tax": tax,
                "monthly_hoa": hoa,
            },
        }
    )


def test_fixed_down_payment_and_independently_checked_amortization() -> None:
    result = calculate_financials(calculation(), assumptions())

    assert result.down_payment.amount == Decimal("100000.00")
    assert result.down_payment.percent == Decimal("20.00")
    assert result.loan_amount == Decimal("400000.00")
    assert result.monthly_principal_and_interest.low == Decimal("2398.20")
    assert result.monthly_principal_and_interest.high == Decimal("2398.20")
    assert result.monthly_property_tax == Decimal("500.00")
    assert result.monthly_hoa == Decimal("0.00")
    assert not result.total_is_partial


def test_percentage_down_payment_and_ranges_remain_ordered() -> None:
    result = calculate_financials(
        calculation(mode="percent", down_payment="12.5"),
        assumptions(low="0", high="0.075"),
    )

    assert result.down_payment.amount == Decimal("62500.00")
    assert result.down_payment.percent == Decimal("12.50")
    assert result.monthly_principal_and_interest.low < result.monthly_principal_and_interest.high
    assert result.estimated_monthly_housing_total.low <= result.estimated_monthly_housing_total.high
    assert (
        result.current_income.monthly_gross_balance_after_housing_and_travel.low
        <= result.current_income.monthly_gross_balance_after_housing_and_travel.high
    )


def test_unknown_is_not_zero_and_zero_income_has_no_ratio() -> None:
    result = calculate_financials(
        calculation(tax=None, hoa=None, current_income="0"), assumptions()
    )

    assert result.monthly_property_tax is None
    assert result.monthly_hoa is None
    assert result.unknown_components == ["property_tax", "hoa"]
    assert result.total_is_partial
    assert result.current_income.housing_percent is None


def test_excessive_down_payment_is_rejected() -> None:
    with pytest.raises(FinancialCalculationError, match="cannot exceed"):
        calculate_financials(calculation(down_payment="500001"), assumptions())


@pytest.mark.anyio
async def test_finance_api_uses_configured_assumptions(tmp_path: Path) -> None:
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    config["profile_file"] = str(tmp_path / "profile.yaml")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = create_app(config_path=config_path, database_path=tmp_path / "app.db")

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/finance/calculate", json=calculation().model_dump(mode="json")
        )

    assert response.status_code == 200
    assert response.json()["down_payment"] == {
        "authoritative_mode": "amount",
        "amount": "100000.00",
        "percent": "20.00",
    }
