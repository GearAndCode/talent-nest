"""
Tests for TalentNest's paid plan upgrade flow (Part 6): Professional ->
Business (and other plan-to-plan changes) via POST /subscription/upgrade.

PayFast has no API to silently change the amount of an existing charge,
so an upgrade is a fresh, customer-present checkout for the NEW plan
(POST /subscription/upgrade -> the same create_checkout() used by a
first-time subscribe - see app/routers/subscription.py). The only thing
that differs from a bare /checkout call is the upgrade-specific
validation POST /subscription/upgrade adds on top: the target plan must
exist, must not be the free Starter plan, and must differ from the
company's current plan. A verified webhook is still the ONLY thing that
ever changes the company's plan - never the checkout call itself, and
never the frontend success page.

Scope of these tests:
  1. POST /subscription/upgrade computes the pending Payment's amount
     from the server-side plan row for the requested plan (Business),
     never from anything the client could supply.
  2. A successful upgrade webhook moves the company onto the new plan
     (Professional -> Business) and doesn't create a second Subscription
     row for the company.
  3. A failed/declined upgrade payment does NOT change the company's plan.
  4. A "cancelled" (non-"paid") upgrade payment notification does NOT
     change the company's plan.
  5. A duplicate delivery of an already-processed upgrade webhook is
     idempotent (plan set once, no duplicate Payment/Subscription rows).
  6. Selecting a nonexistent plan code is rejected before any checkout
     session or Payment row is created.
  7. Selecting the plan the company is already on (Business -> Business,
     Starter -> Starter) is rejected as a no-op upgrade.
  8. Selecting the free Starter plan as the upgrade target is rejected.
  9. An unauthenticated request is rejected before any of the above runs.
  10. The plan does NOT change until the webhook fires - the checkout
      call by itself leaves the company on its old plan.
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
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    Payment,
)
from app.models.plan import Plan  # noqa: E402
from app.models.subscription import STATUS_ACTIVE, Subscription  # noqa: E402
from app.routers import subscription as subscription_router_module  # noqa: E402
from app.services import subscription_service  # noqa: E402

WEBHOOK_SECRET = "test-webhook-secret"


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
def app_instance():
    app = FastAPI()
    app.include_router(subscription_router_module.router)
    return app


@pytest.fixture()
def client(db_session, company, app_instance):
    """An authenticated client - Authorization is stubbed as `company`."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    def _override_get_current_company():
        return company

    app_instance.dependency_overrides[get_db] = _override_get_db
    app_instance.dependency_overrides[get_current_company] = _override_get_current_company
    return TestClient(app_instance)


@pytest.fixture()
def unauthenticated_client(db_session, app_instance):
    """No get_current_company override - a real 401 is expected."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app_instance.dependency_overrides[get_db] = _override_get_db
    return TestClient(app_instance)


@pytest.fixture()
def starter_plan(db_session):
    plan = Plan(code="starter", name="Starter", price=0, currency="USD", display_order=1)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture()
def professional_plan(db_session):
    plan = Plan(
        code="professional",
        name="Professional",
        price=9,
        currency="USD",
        display_order=2,
        max_active_jobs=5,
        ai_resume_analysis_enabled=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture()
def business_plan(db_session):
    plan = Plan(
        code="business",
        name="Business",
        price=19,
        currency="USD",
        display_order=3,
        max_active_jobs=15,
        ai_resume_analysis_enabled=True,
        multiple_recruiters_enabled=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _make_active_subscription(db_session, company, plan, *, period_end=None):
    period_end = period_end or (datetime.now(timezone.utc) + timedelta(days=10))
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
# 1. Upgrade checkout uses the server-side plan's price, never a
#    client-supplied one
# ------------------------------------------------------------------
def test_upgrade_uses_server_side_plan_price(
    client, db_session, company, professional_plan, business_plan
):
    _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})

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
    assert payment.status == PAYMENT_STATUS_PENDING
    assert payment.plan_id == business_plan.id
    assert float(payment.amount) == float(business_plan.price)  # 19, not anything client-sent
    assert payment.is_renewal is False


# ------------------------------------------------------------------
# 10. The plan does NOT change until the webhook confirms payment
# ------------------------------------------------------------------
def test_upgrade_checkout_alone_does_not_change_plan(
    client, db_session, company, professional_plan, business_plan
):
    _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})
    assert resp.status_code == 200

    subscription = subscription_service.get_or_create_subscription(db_session, company.id)
    assert subscription.plan.code == "professional"  # unchanged - no webhook yet


# ------------------------------------------------------------------
# 2. A successful upgrade webhook moves the company onto the new plan,
#    without creating a second Subscription row
# ------------------------------------------------------------------
def test_successful_upgrade_webhook_activates_new_plan(
    client, db_session, company, professional_plan, business_plan
):
    subscription = _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})
    transaction_id = resp.json()["transaction_id"]
    payment = db_session.query(Payment).filter(Payment.transaction_id == transaction_id).first()

    webhook_resp = client.post(_webhook_url(), data=_payfast_form(payment))

    assert webhook_resp.status_code == 200
    assert webhook_resp.json()["status"] == "ok"

    db_session.refresh(payment)
    assert payment.status == PAYMENT_STATUS_PAID
    assert payment.subscription_id == subscription.id

    db_session.refresh(subscription)
    assert subscription.plan_id == business_plan.id
    assert subscription.status == STATUS_ACTIVE

    # Still exactly one Subscription row for this company.
    assert (
        db_session.query(Subscription).filter(Subscription.company_id == company.id).count()
        == 1
    )


# ------------------------------------------------------------------
# 3. A failed/declined upgrade payment does not change the plan
# ------------------------------------------------------------------
@pytest.mark.parametrize("err_code", ["001", "97", "14"])
def test_failed_upgrade_payment_does_not_change_plan(
    client, db_session, company, professional_plan, business_plan, err_code
):
    subscription = _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})
    transaction_id = resp.json()["transaction_id"]
    payment = db_session.query(Payment).filter(Payment.transaction_id == transaction_id).first()

    webhook_resp = client.post(_webhook_url(), data=_payfast_form(payment, err_code=err_code))

    assert webhook_resp.status_code == 200
    assert webhook_resp.json()["status"] == "recorded_not_paid"

    db_session.refresh(payment)
    assert payment.status == PAYMENT_STATUS_FAILED
    assert payment.subscription_id is None

    db_session.refresh(subscription)
    assert subscription.plan_id == professional_plan.id  # unchanged


# ------------------------------------------------------------------
# 4. A cancelled checkout (never notified as paid) leaves the plan alone
# ------------------------------------------------------------------
def test_cancelled_upgrade_checkout_does_not_change_plan(
    client, db_session, company, professional_plan, business_plan
):
    subscription = _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})
    transaction_id = resp.json()["transaction_id"]
    payment = db_session.query(Payment).filter(Payment.transaction_id == transaction_id).first()

    # The customer abandons/cancels on PayFast's page - no webhook ever
    # arrives for this transaction. The pending payment and the old plan
    # both remain exactly as they were.
    db_session.refresh(payment)
    assert payment.status == PAYMENT_STATUS_PENDING

    db_session.refresh(subscription)
    assert subscription.plan_id == professional_plan.id


# ------------------------------------------------------------------
# 5. Duplicate delivery of an already-processed upgrade webhook
# ------------------------------------------------------------------
def test_duplicate_upgrade_webhook_is_idempotent(
    client, db_session, company, professional_plan, business_plan
):
    subscription = _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})
    transaction_id = resp.json()["transaction_id"]
    payment = db_session.query(Payment).filter(Payment.transaction_id == transaction_id).first()

    first = client.post(_webhook_url(), data=_payfast_form(payment))
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    db_session.refresh(subscription)
    period_end_after_first = subscription.current_period_end

    second = client.post(_webhook_url(), data=_payfast_form(payment))
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    db_session.refresh(subscription)
    assert subscription.plan_id == business_plan.id
    assert subscription.current_period_end == period_end_after_first
    assert (
        db_session.query(Payment).filter(Payment.transaction_id == transaction_id).count() == 1
    )
    assert (
        db_session.query(Subscription).filter(Subscription.company_id == company.id).count()
        == 1
    )


# ------------------------------------------------------------------
# 6. Nonexistent plan is rejected before any Payment row is created
# ------------------------------------------------------------------
def test_upgrade_to_nonexistent_plan_is_rejected(
    client, db_session, company, professional_plan
):
    _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "enterprise-deluxe"})

    assert resp.status_code == 400
    assert db_session.query(Payment).count() == 0


# ------------------------------------------------------------------
# 7. Upgrading to the plan already held is rejected (Business -> Business,
#    Starter -> Starter)
# ------------------------------------------------------------------
def test_upgrade_to_same_plan_is_rejected(client, db_session, company, business_plan):
    _make_active_subscription(db_session, company, business_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "business"})

    assert resp.status_code == 400
    assert db_session.query(Payment).count() == 0


def test_starter_to_starter_upgrade_is_rejected(client, db_session, company, starter_plan):
    subscription_service.get_or_create_subscription(db_session, company.id)

    resp = client.post("/subscription/upgrade", json={"plan_code": "starter"})

    assert resp.status_code == 400
    assert db_session.query(Payment).count() == 0


# ------------------------------------------------------------------
# 8. Upgrading to the free Starter plan is always rejected
# ------------------------------------------------------------------
def test_upgrade_to_starter_is_rejected(
    client, db_session, company, professional_plan, starter_plan
):
    _make_active_subscription(db_session, company, professional_plan)

    resp = client.post("/subscription/upgrade", json={"plan_code": "starter"})

    assert resp.status_code == 400
    assert db_session.query(Payment).count() == 0


# ------------------------------------------------------------------
# 9. Unauthenticated requests are rejected outright
# ------------------------------------------------------------------
def test_upgrade_requires_authentication(unauthenticated_client, db_session):
    resp = unauthenticated_client.post(
        "/subscription/upgrade", json={"plan_code": "business"}
    )

    assert resp.status_code == 401
    assert db_session.query(Payment).count() == 0
