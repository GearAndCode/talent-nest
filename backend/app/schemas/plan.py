from typing import List, Optional

from pydantic import BaseModel


class PlanOut(BaseModel):
    """
    Public representation of a single subscription plan.

    `id` is the stable internal plan identifier (e.g. "starter",
    "professional", "business"). This is the value the frontend must send
    when it eventually initiates checkout — never the display name or the
    price, since those are free to change without breaking billing logic.
    """

    id: str
    name: str
    tagline: Optional[str] = None
    price_monthly: float
    currency: str = "USD"
    billing_period: str = "month"
    active_jobs_limit: str
    applications_per_job_limit: str
    features: List[str]
    is_most_popular: bool = False
    cta_label: str

    class Config:
        from_attributes = True
