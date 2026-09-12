from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# Possible payment.status values.
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_CANCELLED = "cancelled"


class Payment(Base):
    """
    A single billing/payment event for a company, used to render Billing
    History in the HR subscription page.

    NOTE: this is unrelated to app.models.subscriber.Subscriber, which is
    the public newsletter email list - not billing.
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)

    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)

    amount = Column(Numeric(10, 2), nullable=False)

    currency = Column(String(10), nullable=False, default="USD")

    status = Column(String(20), nullable=False, default=PAYMENT_STATUS_PENDING)

    payment_provider = Column(String(50), nullable=True)

    # The payment gateway's unique transaction/order reference. Used to make
    # webhook processing idempotent (a duplicate webhook for the same
    # transaction_id must never create a second payment row).
    transaction_id = Column(String(150), nullable=True, unique=True, index=True)

    # True for a renewal payment (a company paying to extend its existing
    # paid subscription for another period, see POST /subscription/renew).
    # False for a first-time subscribe or a plan upgrade/downgrade
    # (POST /checkout, POST /subscription/upgrade). The webhook handler
    # uses this to decide whether a successful payment should EXTEND the
    # existing current_period_end (renewal) or START a fresh period from
    # now (first subscribe / upgrade) - see app.services.subscription_service.
    is_renewal = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company")

    subscription = relationship("Subscription", back_populates="payments")

    plan = relationship("Plan")
