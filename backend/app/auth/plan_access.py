from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.oauth2 import get_current_company
from app.database import get_db
from app.models.company import Company
from app.models.subscription import ACTIVE_STATUSES, Subscription
from app.services import subscription_service


def get_current_subscription(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
) -> Subscription:
    """
    Resolves (and lazily creates, on Starter) the calling company's
    subscription. Use this directly when a route just needs to read plan
    info; use require_feature()/require_active_plan() below when a route
    must reject requests that lack an entitlement.
    """
    return subscription_service.get_or_create_subscription(db, company.id)


def require_feature(feature: str):
    """
    FastAPI dependency factory that blocks the request unless the calling
    company's ACTIVE subscription's plan has `feature` enabled.

    Usage:
        @router.get("/applications/jobs/{job_id}/ranked-candidates")
        def ranked_candidates(
            ...,
            subscription: Subscription = Depends(require_feature("ai_candidate_ranking_enabled")),
        ):
            ...

    Returns 402 Payment Required (not 403) so the frontend can reliably
    distinguish "you're not allowed, ever" from "upgrade to unlock this",
    and render the polished upgrade UI instead of a generic error.
    """

    def dependency(
        company: Company = Depends(get_current_company),
        db: Session = Depends(get_db),
    ) -> Subscription:
        subscription = subscription_service.get_or_create_subscription(db, company.id)

        if subscription.status not in ACTIVE_STATUSES or not getattr(
            subscription.plan, feature, False
        ):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "premium_feature_required",
                    "feature": feature,
                    "current_plan": subscription.plan.code,
                    "message": (
                        "This feature requires a Professional or Business "
                        "subscription. Upgrade to unlock it."
                    ),
                },
            )

        return subscription

    return dependency


def enforce_active_job_limit(db: Session, company: Company) -> None:
    """
    Called from POST /jobs before a new job is created. Raises 402 if the
    company's plan limit on active jobs has already been reached.
    """
    subscription = subscription_service.get_or_create_subscription(db, company.id)
    plan = subscription.plan

    current_count = subscription_service.count_active_jobs(db, company.id)

    if current_count >= plan.max_active_jobs:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "job_limit_reached",
                "limit": plan.max_active_jobs,
                "current_plan": plan.code,
                "message": (
                    f"Your {plan.name} plan allows up to {plan.max_active_jobs} "
                    "active job(s). Upgrade your plan to post more jobs."
                ),
            },
        )


def enforce_application_limit(db: Session, company: Company, current_application_count: int) -> None:
    """
    Called from the candidate-facing apply endpoint before a new
    application is recorded against a job, using that job's owning
    company's plan.
    """
    subscription = subscription_service.get_or_create_subscription(db, company.id)
    plan = subscription.plan

    if current_application_count >= plan.max_applications_per_job:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "application_limit_reached",
                "limit": plan.max_applications_per_job,
                "current_plan": plan.code,
                "message": (
                    f"This job has reached the {plan.max_applications_per_job} "
                    "application limit for its plan."
                ),
            },
        )
