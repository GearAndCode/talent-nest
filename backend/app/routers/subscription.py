import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.oauth2 import get_current_company
from app.config import FRONTEND_BASE_URL
from app.database import get_db
from app.models.company import Company
from app.models.payment import (
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    Payment,
)
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.schemas.subscription import (
    CheckoutRequest,
    CheckoutResponse,
    PaymentResponse,
    PlanResponse,
    SubscriptionResponse,
    SubscriptionUpgradeRequest,
)
from app.services import subscription_service
from app.services.payment.payment_service import get_payment_provider

logger = logging.getLogger("talentnest.routers.subscription")

router = APIRouter(tags=["Subscription & Billing"])


# ------------------------------------------------------------------
# Plans (public - no auth required, powers the pricing page)
# ------------------------------------------------------------------
@router.get("/plans", response_model=list[PlanResponse])
def list_plans(db: Session = Depends(get_db)):
    subscription_service.ensure_plans_seeded(db)
    return (
        db.query(Plan)
        .order_by(Plan.display_order.asc())
        .all()
    )


# ------------------------------------------------------------------
# Current company subscription
# ------------------------------------------------------------------
@router.get("/subscription", response_model=SubscriptionResponse)
def get_my_subscription(
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    subscription = subscription_service.get_or_create_subscription(db, company.id)
    active_jobs_used = subscription_service.count_active_jobs(db, company.id)

    response = SubscriptionResponse.model_validate(subscription)
    response.active_jobs_used = active_jobs_used
    return response


# ------------------------------------------------------------------
# Checkout - creates a REAL PayFast checkout session.
#
# The frontend sends only a stable plan_code ("professional"/"business").
# The amount is ALWAYS looked up from the plans table here on the server -
# the client can never influence what gets charged.
# ------------------------------------------------------------------
@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    body: CheckoutRequest,
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    plan = db.query(Plan).filter(Plan.code == body.plan_code).first()
    if not plan:
        raise HTTPException(status_code=400, detail="Unknown plan.")

    if plan.code == subscription_service.FREE_PLAN_CODE:
        raise HTTPException(
            status_code=400,
            detail="The Starter plan is free and does not require checkout.",
        )

    transaction_id = f"tn_{uuid.uuid4().hex[:20]}"

    # Record a PENDING payment up front. The webhook, not this endpoint,
    # is what will ever mark it paid.
    payment = Payment(
        company_id=company.id,
        subscription_id=None,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id=transaction_id,
    )
    db.add(payment)
    db.commit()

    provider = get_payment_provider()

    try:
        session = provider.create_checkout_session(
            company_id=company.id,
            company_email=company.email,
            plan_code=plan.code,
            plan_name=plan.name,
            amount=float(plan.price),
            currency=plan.currency,
            transaction_id=transaction_id,
            return_url=f"{FRONTEND_BASE_URL}/payment-success",
            cancel_url=f"{FRONTEND_BASE_URL}/payment-cancelled",
        )
    except RuntimeError as exc:
        # Provider not configured (missing merchant credentials) - a real,
        # honest error rather than a fake success.
        logger.error(f"Checkout creation failed - provider unavailable: {exc}")
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The payment provider is not configured yet. Please contact "
                "support - no charge has been made."
            ),
        )
    except Exception as exc:
        logger.error(f"Checkout creation failed: {type(exc).__name__}: {exc}")
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout with the payment provider. Please try again.",
        )

    logger.info(
        f"Checkout created - company_id={company.id} plan={plan.code} "
        f"transaction_id={transaction_id}"
    )

    return CheckoutResponse(
        checkout_url=session.checkout_url,
        provider="payfast",
        transaction_id=transaction_id,
    )


# ------------------------------------------------------------------
# Webhook / IPN - the ONLY thing that ever activates a subscription.
# ------------------------------------------------------------------
@router.post("/payment/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    form = None
    try:
        form = dict(await request.form())
    except Exception:
        form = None

    provider = get_payment_provider()

    try:
        event = provider.verify_webhook(
            raw_body, dict(request.headers), form, dict(request.query_params)
        )
    except ValueError as exc:
        logger.warning(f"Webhook verification failed: {exc}")
        raise HTTPException(status_code=400, detail="Invalid webhook request.")

    # Lock the row so two near-simultaneous deliveries of the same webhook
    # (PayFast retries on anything other than a fast 200) can't both pass
    # the "not yet paid" check below and double-activate a subscription.
    payment = (
        db.query(Payment)
        .filter(Payment.transaction_id == event.transaction_id)
        .with_for_update()
        .first()
    )
    if not payment:
        logger.warning(f"Webhook for unknown transaction_id={event.transaction_id}")
        raise HTTPException(status_code=404, detail="Unknown transaction.")

    # Idempotency: if this transaction has already been marked paid, a
    # duplicate webhook delivery is a harmless no-op - never a second
    # payment or a second subscription activation.
    if payment.status == PAYMENT_STATUS_PAID:
        logger.info(f"Duplicate webhook ignored for transaction_id={event.transaction_id}")
        return {"status": "already_processed"}

    # The reported amount must match what we actually asked the customer
    # to pay for this transaction. A mismatch means either a bug on
    # PayFast's side or a tampered/incorrect notification - either way we
    # must not activate anything on the strength of it.
    if event.amount is not None and abs(float(payment.amount) - event.amount) > 0.01:
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        logger.warning(
            f"Webhook amount mismatch for transaction_id={event.transaction_id}: "
            f"expected={payment.amount} got={event.amount}"
        )
        raise HTTPException(status_code=400, detail="Amount mismatch.")

    if event.status != "paid":
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        logger.info(f"Webhook reports non-paid status for transaction_id={event.transaction_id}")
        return {"status": "recorded_not_paid"}

    plan = db.query(Plan).filter(Plan.id == payment.plan_id).first()
    if not plan:
        logger.error(f"Payment {payment.id} references missing plan_id={payment.plan_id}")
        raise HTTPException(status_code=500, detail="Plan not found for this payment.")

    if payment.is_renewal:
        # Renewal: extend the company's EXISTING subscription period
        # rather than starting a fresh one from "now" - see
        # subscription_service.renew_subscription for why. This never
        # creates a second Subscription row: get_or_create_subscription
        # returns the company's single subscription (unique on
        # company_id), which is then updated in place.
        subscription = subscription_service.get_or_create_subscription(db, payment.company_id)
        subscription = subscription_service.renew_subscription(
            db,
            subscription=subscription,
            plan=plan,
            payment_provider="payfast",
        )
        log_verb = "renewed"
    else:
        subscription = subscription_service.activate_subscription(
            db,
            company_id=payment.company_id,
            plan=plan,
            payment_provider="payfast",
            customer_id=None,
            provider_subscription_id=event.transaction_id,
        )
        log_verb = "activated"

    payment.status = PAYMENT_STATUS_PAID
    payment.subscription_id = subscription.id
    db.commit()

    logger.info(
        f"Subscription {log_verb} via webhook - company_id={payment.company_id} "
        f"plan={plan.code} transaction_id={event.transaction_id}"
    )

    return {"status": "ok"}


# ------------------------------------------------------------------
# Cancel / upgrade
# ------------------------------------------------------------------
@router.post("/subscription/cancel", response_model=SubscriptionResponse)
def cancel_my_subscription(
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    subscription = subscription_service.get_or_create_subscription(db, company.id)
    already_cancelled = subscription.cancel_at_period_end
    was_paid = subscription.plan.code != subscription_service.FREE_PLAN_CODE

    subscription = subscription_service.cancel_subscription(db, subscription)

    # Best-effort provider-side mirror. Our local cancel_at_period_end is
    # always the source of truth for entitlement (see
    # subscription_service.cancel_subscription), so a provider that has
    # nothing to cancel (PayFast, currently) or that errors out here must
    # never block or reverse the cancellation that already happened above.
    # Skipped on a repeat call (idempotency) and on the free plan (nothing
    # was ever cancelled).
    if was_paid and not already_cancelled and subscription.payment_provider:
        try:
            provider = get_payment_provider()
            provider.cancel_provider_subscription(subscription.subscription_id)
        except Exception as exc:
            logger.warning(
                f"Provider-side cancellation failed for company_id={company.id}: "
                f"{type(exc).__name__}: {exc}"
            )

    response = SubscriptionResponse.model_validate(subscription)
    response.active_jobs_used = subscription_service.count_active_jobs(db, company.id)
    return response


@router.post("/subscription/upgrade", response_model=CheckoutResponse)
def upgrade_my_subscription(
    body: SubscriptionUpgradeRequest,
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    """
    Move the calling company onto a different paid plan (e.g.
    Professional -> Business) via a real PayFast checkout - PayFast has
    no API to silently change the amount of an existing charge, so a
    plan change is always a new, customer-present transaction (see
    create_checkout). create_checkout independently re-verifies the
    target plan and looks its price up from the database, so the
    frontend can never influence what actually gets charged.

    This endpoint adds upgrade-specific guardrails on top of that:
      - the target plan must exist,
      - the target plan can't be the free Starter plan (there is nothing
        to check out for that - see /subscription/cancel to move to
        Starter at the end of the current period),
      - the target plan can't be the plan the company is already on
        (e.g. Professional -> Professional, or Starter -> Starter, is
        not a meaningful upgrade).

    Just like a first-time subscribe, a successful checkout here does
    NOT change the company's plan by itself - only a verified webhook
    (see payment_webhook below, which activates via
    subscription_service.activate_subscription) does that. This also
    means no duplicate Subscription row is ever created: activate_
    subscription updates the company's single existing row in place.
    """
    subscription = subscription_service.get_or_create_subscription(db, company.id)

    plan = db.query(Plan).filter(Plan.code == body.plan_code).first()
    if not plan:
        raise HTTPException(status_code=400, detail="Unknown plan.")

    if plan.code == subscription_service.FREE_PLAN_CODE:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot upgrade to the free Starter plan. Cancel your "
                "subscription instead to move to Starter at the end of "
                "your current billing period."
            ),
        )

    if plan.code == subscription.plan.code:
        raise HTTPException(
            status_code=400,
            detail=f"You are already on the {plan.name} plan.",
        )

    return create_checkout(
        CheckoutRequest(plan_code=body.plan_code), db=db, company=company
    )


# ------------------------------------------------------------------
# Renewal.
#
# PayFast Pakistan's hosted-checkout integration used here (see
# app/services/payment/payfast_provider.py) has no tokenized/automatic
# recurring-billing API - each GetAccessToken/PostTransaction round trip
# is a one-off, customer-present transaction. So a "renewal" is a new
# checkout for the SAME plan the company is already on, going through the
# exact same documented hosted-checkout flow as /checkout - never an
# invented auto-charge. The only thing that differs from a normal
# checkout is what happens once the webhook confirms payment: the
# existing subscription period gets EXTENDED (see
# subscription_service.renew_subscription) instead of restarted.
# ------------------------------------------------------------------
@router.post("/subscription/renew", response_model=CheckoutResponse)
def renew_my_subscription(
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    subscription = subscription_service.get_or_create_subscription(db, company.id)

    if not subscription_service.is_renewable(subscription):
        raise HTTPException(
            status_code=400,
            detail=(
                "There is no active paid subscription to renew. "
                "Choose a plan to subscribe instead."
            ),
        )

    # Always renew whatever plan the company is CURRENTLY on and charge
    # the amount from the plans table - a renewal can never be used to
    # sneak in a plan change or a client-controlled amount. Plan changes
    # still go through /subscription/upgrade, untouched by this endpoint.
    plan = subscription.plan

    transaction_id = f"tn_{uuid.uuid4().hex[:20]}"

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id=transaction_id,
        is_renewal=True,
    )
    db.add(payment)
    db.commit()

    provider = get_payment_provider()

    try:
        session = provider.create_checkout_session(
            company_id=company.id,
            company_email=company.email,
            plan_code=plan.code,
            plan_name=plan.name,
            amount=float(plan.price),
            currency=plan.currency,
            transaction_id=transaction_id,
            return_url=f"{FRONTEND_BASE_URL}/payment-success",
            cancel_url=f"{FRONTEND_BASE_URL}/payment-cancelled",
        )
    except RuntimeError as exc:
        logger.error(f"Renewal checkout creation failed - provider unavailable: {exc}")
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The payment provider is not configured yet. Please contact "
                "support - no charge has been made."
            ),
        )
    except Exception as exc:
        logger.error(f"Renewal checkout creation failed: {type(exc).__name__}: {exc}")
        payment.status = PAYMENT_STATUS_FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout with the payment provider. Please try again.",
        )

    logger.info(
        f"Renewal checkout created - company_id={company.id} plan={plan.code} "
        f"transaction_id={transaction_id}"
    )

    return CheckoutResponse(
        checkout_url=session.checkout_url,
        provider="payfast",
        transaction_id=transaction_id,
    )


# ------------------------------------------------------------------
# Billing history
# ------------------------------------------------------------------
@router.get("/payments", response_model=list[PaymentResponse])
def list_my_payments(
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company),
):
    payments = (
        db.query(Payment)
        .filter(Payment.company_id == company.id)
        .order_by(Payment.created_at.desc())
        .all()
    )

    results = []
    for p in payments:
        item = PaymentResponse.model_validate(p)
        item.plan_name = p.plan.name if p.plan else None
        results.append(item)
    return results
