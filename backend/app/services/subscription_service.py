from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import (
    ACTIVE_STATUSES,
    STATUS_ACTIVE,
    Subscription,
)
from app.models.job import Job

# ------------------------------------------------------------------
# Plan catalog (single source of truth for backend authorization).
#
# The frontend has its own copy of this display data (src/config/plans.js)
# for rendering the pricing page instantly without a network round trip,
# but every actual authorization/limit decision is made from THESE rows in
# the database, seeded from this exact table at startup. If the two ever
# need to diverge, this dict wins.
# ------------------------------------------------------------------
PLAN_CATALOG = [
    {
        "code": "starter",
        "name": "Starter",
        "price": 0,
        "currency": "USD",
        "billing_interval": "month",
        "is_most_popular": False,
        "max_active_jobs": 1,
        "max_applications_per_job": 25,
        "max_recruiters": 1,
        "ai_resume_analysis_enabled": False,
        "ai_candidate_ranking_enabled": False,
        "ai_recommendations_enabled": False,
        "ai_interview_questions_enabled": False,
        "advanced_analytics_enabled": False,
        "multiple_recruiters_enabled": False,
        "display_order": 1,
    },
    {
        "code": "professional",
        "name": "Professional",
        "price": 9,
        "currency": "USD",
        "billing_interval": "month",
        "is_most_popular": True,
        "max_active_jobs": 5,
        "max_applications_per_job": 200,
        "max_recruiters": 1,
        "ai_resume_analysis_enabled": True,
        "ai_candidate_ranking_enabled": True,
        "ai_recommendations_enabled": True,
        "ai_interview_questions_enabled": True,
        "advanced_analytics_enabled": True,
        "multiple_recruiters_enabled": False,
        "display_order": 2,
    },
    {
        "code": "business",
        "name": "Business",
        "price": 19,
        "currency": "USD",
        "billing_interval": "month",
        "is_most_popular": False,
        "max_active_jobs": 15,
        "max_applications_per_job": 1000,
        "max_recruiters": 10,
        "ai_resume_analysis_enabled": True,
        "ai_candidate_ranking_enabled": True,
        "ai_recommendations_enabled": True,
        "ai_interview_questions_enabled": True,
        "advanced_analytics_enabled": True,
        "multiple_recruiters_enabled": True,
        "display_order": 3,
    },
]

FREE_PLAN_CODE = "starter"


def ensure_plans_seeded(db: Session) -> None:
    """
    Idempotently seed/refresh the three plan rows from PLAN_CATALOG. Safe to
    call on every app startup. Existing subscriptions keep pointing at the
    same plan row (matched by `code`), so re-running this after tweaking a
    limit updates every subscriber on that plan immediately.
    """
    for entry in PLAN_CATALOG:
        plan = db.query(Plan).filter(Plan.code == entry["code"]).first()
        if plan is None:
            db.add(Plan(**entry))
        else:
            for key, value in entry.items():
                setattr(plan, key, value)
    db.commit()


def get_free_plan(db: Session) -> Plan:
    plan = db.query(Plan).filter(Plan.code == FREE_PLAN_CODE).first()
    if plan is None:
        # Extremely defensive fallback in case seeding hasn't run yet.
        ensure_plans_seeded(db)
        plan = db.query(Plan).filter(Plan.code == FREE_PLAN_CODE).first()
    return plan


def get_or_create_subscription(db: Session, company_id: int) -> Subscription:
    """
    Every company should have exactly one subscription row. New companies
    (and any pre-existing companies from before this feature shipped) are
    lazily enrolled onto the free Starter plan the first time they're
    looked up, so nothing in the rest of the app has to special-case a
    missing subscription.
    """
    subscription = (
        db.query(Subscription).filter(Subscription.company_id == company_id).first()
    )
    if subscription:
        _apply_expiry_if_needed(db, subscription)
        return subscription

    free_plan = get_free_plan(db)
    subscription = Subscription(
        company_id=company_id,
        plan_id=free_plan.id,
        status=STATUS_ACTIVE,
        payment_provider=None,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def _apply_expiry_if_needed(db: Session, subscription: Subscription) -> None:
    """
    A paid subscription reverts to Starter once current_period_end has
    passed - whether the company explicitly clicked Cancel
    (cancel_at_period_end=True) or simply let the period lapse without
    renewing. PayFast's hosted-checkout integration has no auto-charge
    (see payfast_provider.py / subscription_service.renew_subscription),
    so there is no such thing as a period ending "successfully" without a
    new payment: once `now` passes `current_period_end` with no renewal
    having extended it, the paid period is over and access must end.

    This is checked lazily on every read (get_or_create_subscription)
    rather than via a cron job/scheduler. That is sufficient for v1's
    scale, avoids adding a background scheduler, AND means expiry is
    enforced everywhere a subscription is resolved - job posting,
    application limits, feature gates, the /subscription endpoint - not
    only when the billing page happens to be opened.

    Idempotent: downgrade_to_free() clears current_period_end, so a
    second call against an already-downgraded subscription returns
    immediately above (period_end is None) and does nothing further.
    """
    now = datetime.now(timezone.utc)
    period_end = subscription.current_period_end

    if period_end is None:
        return

    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    if subscription.status in ACTIVE_STATUSES and now > period_end:
        downgrade_to_free(db, subscription)


def downgrade_to_free(db: Session, subscription: Subscription) -> Subscription:
    free_plan = get_free_plan(db)
    subscription.plan_id = free_plan.id
    # Starter itself is always "active" - it's free, so there's nothing to
    # be past-due or expired on. Only the paid plan the company fell off of
    # concept was "expired"/"cancelled"; the resulting Starter row is active.
    subscription.status = STATUS_ACTIVE
    subscription.payment_provider = None
    subscription.cancel_at_period_end = False
    subscription.current_period_start = None
    subscription.current_period_end = None
    db.commit()
    db.refresh(subscription)
    return subscription


def activate_subscription(
    db: Session,
    *,
    company_id: int,
    plan: Plan,
    payment_provider: str,
    customer_id: str | None,
    provider_subscription_id: str | None,
) -> Subscription:
    """
    Called only from the webhook handler once a payment gateway has
    confirmed a successful payment. This is the single place that flips a
    subscription to active/paid - never the frontend, never the checkout
    redirect.
    """
    subscription = get_or_create_subscription(db, company_id)

    now = datetime.now(timezone.utc)
    period_end = now + timedelta(days=30)

    subscription.plan_id = plan.id
    subscription.status = STATUS_ACTIVE
    subscription.payment_provider = payment_provider
    subscription.customer_id = customer_id
    subscription.subscription_id = provider_subscription_id
    subscription.current_period_start = now
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = False

    db.commit()
    db.refresh(subscription)
    return subscription


def renew_subscription(
    db: Session,
    *,
    subscription: Subscription,
    plan: Plan,
    payment_provider: str,
) -> Subscription:
    """
    Called only from the webhook handler once a payment gateway has
    confirmed a successful RENEWAL payment (see
    app.routers.subscription:payment_webhook and :renew_my_subscription) -
    never from the frontend redirect alone.

    This is deliberately different from activate_subscription() above:
    activate_subscription always starts a brand-new period from "now",
    which is correct for a first-time subscribe or a plan upgrade/
    downgrade, but wrong for a renewal - a company that pays a few days
    *before* its current period ends should keep those unused days, not
    lose them. So a renewal extends from the later of "now" and the
    subscription's current current_period_end:
      - Renewing early/on-time: new period starts where the old one ends,
        so no paid time is lost.
      - Renewing after the period has already lapsed: new period starts
        now, same as a fresh subscribe would.

    Plan features/limits, upgrades, and cancellation are untouched here
    beyond what a genuine renewal implies: the plan being renewed is
    whatever plan the payment was actually charged for (`plan`), and a
    successful renewal payment clears any pending
    cancel_at_period_end, since the company just paid to keep going.
    """
    now = datetime.now(timezone.utc)

    period_end = subscription.current_period_end
    if period_end is not None and period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    period_start = period_end if (period_end is not None and period_end > now) else now
    new_period_end = period_start + timedelta(days=30)

    subscription.plan_id = plan.id
    subscription.status = STATUS_ACTIVE
    subscription.payment_provider = payment_provider
    subscription.current_period_start = period_start
    subscription.current_period_end = new_period_end
    subscription.cancel_at_period_end = False

    db.commit()
    db.refresh(subscription)
    return subscription


def is_renewable(subscription: Subscription) -> bool:
    """
    True if `subscription` is currently on a paid plan and in good enough
    standing to renew (i.e. hasn't already lapsed back to Starter - that
    case is a fresh subscribe via /checkout, not a renewal of anything).
    """
    return (
        subscription.plan is not None
        and subscription.plan.code != FREE_PLAN_CODE
        and subscription.status in ACTIVE_STATUSES
    )


def cancel_subscription(db: Session, subscription: Subscription) -> Subscription:
    """
    Mark cancel_at_period_end so the paid plan (and its features/limits)
    remain usable until the period the company already paid for ends,
    matching how most billing providers behave.
    """
    if subscription.plan.code == FREE_PLAN_CODE:
        # Nothing to cancel on the free plan.
        return subscription

    subscription.cancel_at_period_end = True
    db.commit()
    db.refresh(subscription)
    return subscription


def count_active_jobs(db: Session, company_id: int) -> int:
    return db.query(Job).filter(Job.company_id == company_id).count()


def has_feature(subscription: Subscription, feature: str) -> bool:
    if subscription.status not in ACTIVE_STATUSES:
        return False
    return bool(getattr(subscription.plan, feature, False))
