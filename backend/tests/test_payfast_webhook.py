"""
Tests for the PayFast payment webhook (/payment/webhook).

Scope (Part 2 - webhook only): these tests exercise
  1. A genuine, successful PayFast notification -> subscription activated.
  2. An unauthenticated / malformed notification -> rejected, no activation.
  3. A notification reporting a failed/declined payment -> no activation.
  4. A duplicate delivery of an already-processed successful notification
     -> processed once, idempotently (no duplicate Payment/Subscription).
  5. A tampered amount -> rejected, no activation.

The FastAPI app under test only wires up the subscription router (plus a
minimal current-company dependency override) against an in-memory SQLite
database, so these tests don't need Postgres, real PayFast credentials, or
the rest of TalentNest's routers.
"""

import os
import sys

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

from app.database import Base, get_db  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.payment import PAYMENT_STATUS_PAID, PAYMENT_STATUS_PENDING, Payment  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.subscription import Subscription  # noqa: E402
from app.routers import subscription as subscription_router_module  # noqa: E402
from app.services.payment.payfast_provider import PayFastProvider  # noqa: E402

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
def client(db_session):
    app = FastAPI()
    app.include_router(subscription_router_module.router)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


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


@pytest.fixture()
def pending_payment(db_session, company, plan):
    payment = Payment(
        company_id=company.id,
        subscription_id=None,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        status=PAYMENT_STATUS_PENDING,
        payment_provider="payfast",
        transaction_id="tn_test000000000001",
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)
    return payment


def _webhook_url(transaction_id=None, token=WEBHOOK_SECRET):
    url = "/payment/webhook"
    if token is not None:
        url += f"?token={token}"
    return url


def _payfast_form(payment, *, err_code="00", amount=None, transaction_id=None):
    return {
        "BASKET_ID": payment.transaction_id,
        "TRANSACTION_ID": transaction_id or f"PF-{payment.transaction_id}",
        "ERR_CODE": err_code,
        "TXNAMT": f"{amount if amount is not None else payment.amount:.2f}",
    }


# ------------------------------------------------------------------
# 1. Successful, genuine webhook
# ------------------------------------------------------------------
def test_successful_webhook_activates_subscription(client, db_session, pending_payment):
    resp = client.post(_webhook_url(), data=_payfast_form(pending_payment))

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    db_session.refresh(pending_payment)
    assert pending_payment.status == PAYMENT_STATUS_PAID
    assert pending_payment.subscription_id is not None

    subscription = (
        db_session.query(Subscription)
        .filter(Subscription.id == pending_payment.subscription_id)
        .first()
    )
    assert subscription is not None
    assert subscription.status == "active"
    assert subscription.plan_id == pending_payment.plan_id


# ------------------------------------------------------------------
# 2. Invalid / unauthenticated webhook must NOT activate anything
# ------------------------------------------------------------------
def test_missing_token_is_rejected(client, db_session, pending_payment):
    # No shared-secret token at all - PayFast doesn't sign this
    # notification, so the token is the only thing standing between a
    # genuine callback and anyone who guesses a BASKET_ID.
    resp = client.post(_webhook_url(token=None), data=_payfast_form(pending_payment))

    assert resp.status_code == 400

    db_session.refresh(pending_payment)
    assert pending_payment.status == PAYMENT_STATUS_PENDING


def test_wrong_token_is_rejected(client, db_session, pending_payment):
    resp = client.post(
        _webhook_url(token="not-the-real-secret"), data=_payfast_form(pending_payment)
    )

    assert resp.status_code == 400

    db_session.refresh(pending_payment)
    assert pending_payment.status == PAYMENT_STATUS_PENDING


def test_malformed_payload_is_rejected(client, db_session, pending_payment):
    # Valid token, but missing the required BASKET_ID/ERR_CODE fields.
    resp = client.post(_webhook_url(), data={"foo": "bar"})

    assert resp.status_code == 400

    db_session.refresh(pending_payment)
    assert pending_payment.status == PAYMENT_STATUS_PENDING


def test_unknown_transaction_is_rejected(client, db_session):
    resp = client.post(
        _webhook_url(),
        data={"BASKET_ID": "tn_does_not_exist", "ERR_CODE": "00", "TXNAMT": "9.00"},
    )

    assert resp.status_code == 404


def test_tampered_amount_is_rejected(client, db_session, pending_payment):
    # Same transaction id, but the amount PayFast reports doesn't match
    # what we actually charged for - must not activate.
    resp = client.post(
        _webhook_url(), data=_payfast_form(pending_payment, amount=0.01)
    )

    assert resp.status_code == 400

    db_session.refresh(pending_payment)
    assert pending_payment.status != PAYMENT_STATUS_PAID
    assert pending_payment.subscription_id is None


# ------------------------------------------------------------------
# 3. Failed / declined / cancelled payment must NOT activate anything
# ------------------------------------------------------------------
@pytest.mark.parametrize("err_code", ["001", "002", "97", "14", "55"])
def test_failed_payment_does_not_activate_subscription(
    client, db_session, pending_payment, err_code
):
    resp = client.post(
        _webhook_url(), data=_payfast_form(pending_payment, err_code=err_code)
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded_not_paid"

    db_session.refresh(pending_payment)
    assert pending_payment.status == "failed"
    assert pending_payment.subscription_id is None

    assert db_session.query(Subscription).count() == 0


# ------------------------------------------------------------------
# 4. Duplicate delivery of a successful webhook is idempotent
# ------------------------------------------------------------------
def test_duplicate_successful_webhook_is_idempotent(client, db_session, pending_payment):
    first = client.post(_webhook_url(), data=_payfast_form(pending_payment))
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    db_session.refresh(pending_payment)
    subscription_id_after_first = pending_payment.subscription_id
    assert subscription_id_after_first is not None

    # PayFast (or a naive retry) delivers the exact same notification again.
    second = client.post(_webhook_url(), data=_payfast_form(pending_payment))
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    db_session.refresh(pending_payment)
    assert pending_payment.subscription_id == subscription_id_after_first

    # Still exactly one payment row and one subscription row - no
    # duplicates were created by the second delivery.
    assert db_session.query(Payment).count() == 1
    assert db_session.query(Subscription).count() == 1


# ------------------------------------------------------------------
# 5. Provider unit tests - field parsing / status mapping in isolation
# ------------------------------------------------------------------
def test_provider_verify_webhook_paid():
    provider = PayFastProvider()
    event = provider.verify_webhook(
        payload=b"",
        headers={},
        form={"BASKET_ID": "tn_abc", "TRANSACTION_ID": "PF-1", "ERR_CODE": "00", "TXNAMT": "9.00"},
        query={"token": WEBHOOK_SECRET},
    )
    assert event.transaction_id == "tn_abc"
    assert event.status == "paid"
    assert event.amount == 9.00


def test_provider_verify_webhook_failed_status():
    provider = PayFastProvider()
    event = provider.verify_webhook(
        payload=b"",
        headers={},
        form={"BASKET_ID": "tn_abc", "ERR_CODE": "97", "TXNAMT": "9.00"},
        query={"token": WEBHOOK_SECRET},
    )
    assert event.status == "failed"


def test_provider_verify_webhook_bad_token_raises():
    provider = PayFastProvider()
    with pytest.raises(ValueError):
        provider.verify_webhook(
            payload=b"",
            headers={},
            form={"BASKET_ID": "tn_abc", "ERR_CODE": "00", "TXNAMT": "9.00"},
            query={"token": "wrong"},
        )


def test_provider_verify_webhook_malformed_amount_raises():
    provider = PayFastProvider()
    with pytest.raises(ValueError):
        provider.verify_webhook(
            payload=b"",
            headers={},
            form={"BASKET_ID": "tn_abc", "ERR_CODE": "00", "TXNAMT": "not-a-number"},
            query={"token": WEBHOOK_SECRET},
        )
