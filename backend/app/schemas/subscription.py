from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PlanResponse(BaseModel):
    id: int
    code: str
    name: str
    price: float
    currency: str
    billing_interval: str
    is_most_popular: bool

    max_active_jobs: int
    max_applications_per_job: int
    max_recruiters: int

    ai_resume_analysis_enabled: bool
    ai_candidate_ranking_enabled: bool
    ai_recommendations_enabled: bool
    ai_interview_questions_enabled: bool
    advanced_analytics_enabled: bool
    multiple_recruiters_enabled: bool

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    id: int
    company_id: int
    status: str
    payment_provider: Optional[str] = None
    cancel_at_period_end: bool
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    plan: PlanResponse

    # Live usage, computed at request time (not stored).
    active_jobs_used: int = 0

    class Config:
        from_attributes = True


class CheckoutRequest(BaseModel):
    plan_code: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    provider: str
    transaction_id: str


class SubscriptionUpgradeRequest(BaseModel):
    plan_code: str


class PaymentResponse(BaseModel):
    id: int
    amount: float
    currency: str
    status: str
    payment_provider: Optional[str] = None
    transaction_id: Optional[str] = None
    is_renewal: bool = False
    created_at: datetime
    plan_name: Optional[str] = None

    class Config:
        from_attributes = True
