from typing import List

from fastapi import APIRouter

from app.plan_catalog import get_plan_catalog
from app.schemas.plan import PlanOut

router = APIRouter(
    prefix="/plans",
    tags=["Plans"]
)


@router.get(
    "",
    response_model=List[PlanOut]
)
def list_plans():
    """
    Public endpoint returning the current TalentNest subscription plans.

    No authentication is required — pricing is public information. This
    intentionally does not return any per-company subscription state
    (TalentNest has no subscription/billing records yet), so the frontend
    should treat every visitor as eligible for the normal plan CTAs rather
    than a "Current Plan" state.
    """
    return get_plan_catalog()
