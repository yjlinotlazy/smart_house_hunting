from fastapi import APIRouter, HTTPException, Request

from smart_house_hunting.config.loader import ConfigError, load_config
from smart_house_hunting.finance.calculator import (
    FinancialCalculationError,
    calculate_financials,
)
from smart_house_hunting.finance.models import (
    FinancialCalculationRequest,
    FinancialCalculationResult,
)

router = APIRouter(prefix="/api/finance", tags=["finance"])


@router.post("/calculate")
async def calculate(
    calculation: FinancialCalculationRequest, request: Request
) -> FinancialCalculationResult:
    try:
        assumptions = load_config(request.app.state.config_path).finance
        return calculate_financials(calculation, assumptions)
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except FinancialCalculationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
