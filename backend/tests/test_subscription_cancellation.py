"""
Tests for TalentNest's recurring/renewal subscription payments (Part 4).

PayFast Pakistan's hosted-checkout integration used here has no
tokenized/automatic recurring-billing API (see
app/services/payment/payfast_provider.py), so a "renewal" is a fresh,
customer-present checkout for the SAME plan the company is already on
(POST /subscription/renew), going through the exact same documented
hosted-checkout flow as a first-time /checkout. The only thing that
differs is what happens once the webhook confirms payment: the existing
subscription period is EXTENDED (see
subscription_service.renew_subscription) instead of restarted.

Scope of these tests:
  1. POST /subscription/renew is rejected for a company on the free plan.
  2. POST /subscription/renew creates a pending, is_renewal=True Payment
     for the company's CURRENT plan/amount (never client-controlled).
  3. A successful renewal webhook EXTENDS current_period_end from the
     existing period end (renewing early/on-time keeps unused paid time)
     rather than resetting the period to "now".
  4. A successful renewal webhook after the period has already lapsed
     starts the new period from "now".
  5. A duplicate delivery of an already-processed renewal webhook is
     idempotent (period extended exactly once, no duplicate Payment or
     Subscription rows).
  6. A failed/declined renewal payment does NOT extend the subscription
     period or change its status.
  7. A renewal webhook never creates a second Subscription row for the
     company.
  8. A first-time subscribe / upgrade payment (is_renewal=False) still
     resets the period to "now" exactly as before (Part 1/2 behavior is
     unchanged by this work).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "sandbox")
os.environ["PAYMENT_MERCHANT_ID"] = "test-merchant"
os.environ["PAYMENT_SECRET"] = "test-secured-key"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["BACKEND_BASE_URL"] = "https://backend.example.test"
os.environ["FRONTEND_BASE_URL"] = "https://app.example.test"

from app.auth.oauth2 import get_current_company  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.payment import (  # noqa: E402
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    Payment,
)
from app.models.plan import Plan  # noqa: E402
from app.models.subscription import STATUS_ACTIVE, Subscription  # noqa: E402
from app.routers import subscription as subscription_router_module  # noqa: E402
from app.services import subscription_service  # noqa: E402

WEBHOOK_SECRET = "test-webhook-secret"


def _aware(dt):
    """
    SQLite round-trips a DateTime(timezone=True) value as a naive
    datetime (this is exactly why subscription_service itself
    normalizes tzinfo before comparing - see
    _apply_expiry_if_needed/renew_subscription). Tests need the same
    normalization before comparing a value read back from the DB
    against a timezone-aware value created in the test.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def company(db_session):
    company = Company(
        company_name="Acme Recruiting",
        email="hr@acme.test",
        hashed_password="not-a-real-hash",
    )
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


@pytest.fixture()
def client(db_session, company):
    app = FastAPI()
    app.include_router(subscription_router_module.router)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    def _override_get_current_company():
        return company

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_company] = _override_get_current_company
    return TestClient(app)


@pytest.fixture()
def starter_plan(db_session):
    plan = Plan(code="starter", name="Starter", price=0, currency="USD", display_order=1)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture()
def plan(db_session):
    plan = Plan(
        code="professional",
        name="Professional",
        price=9,
        currency="USD",
        display_order=2,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _make_active_subscription(db_session, company, plan, *, period_end):
    subscription = Subscription(
        company_id=company.id,
        plan_id=plan.id,
        status=STATUS_ACTIVE,
        payment_provider="payfast",
        subscription_id="tn_initial",
        current_period_start=period_end - timedelta(days=30),
        current_period_end=period_end,
        cancel_at_period_end=False,
    )
    db_session.add(subscription)
    db_session.commit()
    db_session.refresh(subscription)
    return subscription


def _webhook_url(token=WEBHOOK_SECRET):
    url = "/payment/webhook"
    if token is not None:
        url += f"?token={token}"
    return url


def _payfast_form(payment, *, err_code="00", amount=None):
    return {
        "BASKET_ID": payment.transaction_id,
        "TRANSACTION_ID": f"PF-{payment.transaction_id}",
        "ERR_CODE": err_code,
        "TXNAMT": f"{amount if amount is not None else payment.amount:.2f}",
    }


# ------------------------------------------------------------------
# 1. /subscription/renew rejects companies with no paid subscription
# ------------------------------------------------------------------
def test_renew_rejected_on_free_plan(client, db_session, company, starter_plan):
    subscription_service.get_or_create_subscription(db_session, company.id)

    resp = client.post("/subscription/renew")

    assert resp.status_code == 400
    assert db_session.query(Payment).count() == 0


# ------------------------------------------------------------------
# 2. /subscription/renew creates a correct pending renewal payment
# ------------------------------------------------------------------
def test_renew_creates_pending_renewal_payment_for_current_plan(
    client, db_session, company, plan
):
    future_end = datetime.now(timezone.utc) + timedelta(days=10)
    _make_active_subscription(db_session, company, plan, period_end=future_end)

    resp = client.post("/subscription/renew")

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "payfast"
    assert body["transaction_id"]

    payment = (
        db_session.query(Payment)
        .filter(Payment.transaction_id == body["transaction_id"])
        .first()
    )
    assert payment is not None
    assert payment.is_renewal is True
    assert payment.status == PAYMENT_STATUS_PENDING
    assert payment.plan_id == plan.id
    assert float(payment.amount) == float(plan.price)


# ------------------------------------------------------------------
# 3. Successful renewal EXTENDS the period from the existing period end
# ------------------------------------------------------------------
def test_successful_renewal_extends_from_existing_period_end(
    client, db_session, company, plan
):
    original_end = datetime.now(timezone.utc) + timedelta(days=5)
    subscription = _make_active_subscription(db_session, company, plan, period_end=original_end)

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_renew_0001",
        is_renewal=True,
    )
    db_session.add(payment)
    db_session.commit()

    resp = client.post(_webhook_url(), data=_payfast_form(payment))

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    db_session.refresh(payment)
    db_session.refresh(subscription)

    assert payment.status == PAYMENT_STATUS_PAID
    assert payment.subscription_id == subscription.id

    # Renewed BEFORE expiry: the new period starts where the old one
    # ended, so the 5 unused days are not lost.
    expected_end = original_end + timedelta(days=30)
    assert abs((_aware(subscription.current_period_end) - expected_end).total_seconds()) < 2
    assert subscription.status == STATUS_ACTIVE

    # No second subscription row was created.
    assert db_session.query(Subscription).count() == 1


# ------------------------------------------------------------------
# 4. Successful renewal AFTER the period lapsed starts from "now"
# ------------------------------------------------------------------
def test_successful_renewal_after_lapse_starts_from_now(client, db_session, company, plan):
    lapsed_end = datetime.now(timezone.utc) - timedelta(days=3)
    subscription = _make_active_subscription(db_session, company, plan, period_end=lapsed_end)

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_renew_0002",
        is_renewal=True,
    )
    db_session.add(payment)
    db_session.commit()

    before = datetime.now(timezone.utc)
    resp = client.post(_webhook_url(), data=_payfast_form(payment))
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200

    db_session.refresh(subscription)

    # New period starts "now" (not from the already-passed old end), so
    # it should land ~30 days from somewhere between `before` and `after`.
    new_end = _aware(subscription.current_period_end)
    assert before + timedelta(days=30) <= new_end <= after + timedelta(days=30, seconds=2)


# ------------------------------------------------------------------
# 5. Duplicate renewal webhook delivery is idempotent
# ------------------------------------------------------------------
def test_duplicate_renewal_webhook_is_idempotent(client, db_session, company, plan):
    original_end = datetime.now(timezone.utc) + timedelta(days=5)
    subscription = _make_active_subscription(db_session, company, plan, period_end=original_end)

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_renew_0003",
        is_renewal=True,
    )
    db_session.add(payment)
    db_session.commit()

    first = client.post(_webhook_url(), data=_payfast_form(payment))
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    db_session.refresh(subscription)
    period_end_after_first = _aware(subscription.current_period_end)

    second = client.post(_webhook_url(), data=_payfast_form(payment))
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    db_session.refresh(subscription)
    assert _aware(subscription.current_period_end) == period_end_after_first

    assert db_session.query(Payment).count() == 1
    assert db_session.query(Subscription).count() == 1


# ------------------------------------------------------------------
# 6. Failed renewal payment must NOT extend the period or change status
# ------------------------------------------------------------------
@pytest.mark.parametrize("err_code", ["001", "97", "14"])
def test_failed_renewal_does_not_extend_subscription(
    client, db_session, company, plan, err_code
):
    original_end = datetime.now(timezone.utc) + timedelta(days=5)
    subscription = _make_active_subscription(db_session, company, plan, period_end=original_end)

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_renew_0004",
        is_renewal=True,
    )
    db_session.add(payment)
    db_session.commit()

    resp = client.post(_webhook_url(), data=_payfast_form(payment, err_code=err_code))

    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded_not_paid"

    db_session.refresh(payment)
    db_session.refresh(subscription)

    assert payment.status == "failed"
    # Subscription period/status must be untouched by the failed renewal.
    assert _aware(subscription.current_period_end) == original_end
    assert subscription.status == STATUS_ACTIVE


def test_tampered_renewal_amount_is_rejected(client, db_session, company, plan):
    original_end = datetime.now(timezone.utc) + timedelta(days=5)
    subscription = _make_active_subscription(db_session, company, plan, period_end=original_end)

    payment = Payment(
        company_id=company.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_renew_0005",
        is_renewal=True,
    )
    db_session.add(payment)
    db_session.commit()

    resp = client.post(_webhook_url(), data=_payfast_form(payment, amount=0.01))

    assert resp.status_code == 400

    db_session.refresh(payment)
    db_session.refresh(subscription)
    assert payment.status != PAYMENT_STATUS_PAID
    assert _aware(subscription.current_period_end) == original_end


# ------------------------------------------------------------------
# 7. First-time subscribe / upgrade behavior (is_renewal=False) is
#    unchanged: it still resets the period to "now".
# ------------------------------------------------------------------
def test_non_renewal_payment_still_resets_period_to_now(client, db_session, company, plan):
    transaction_id = "tn_initial_0001"
    payment = Payment(
        company_id=company.id,
        subscription_id=None,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id=transaction_id,
        is_renewal=False,
    )
    db_session.add(payment)
    db_session.commit()

    before = datetime.now(timezone.utc)
    resp = client.post(_webhook_url(), data=_payfast_form(payment))
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200

    subscription = (
        db_session.query(Subscription).filter(Subscription.company_id == company.id).first()
    )
    assert subscription is not None
    assert before <= _aware(subscription.current_period_start) <= after
    new_end = _aware(subscription.current_period_end)
    assert before + timedelta(days=30) <= new_end <= after + timedelta(days=30, seconds=2)
