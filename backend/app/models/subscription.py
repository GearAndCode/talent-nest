from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# Possible subscription.status values.
STATUS_ACTIVE = "active"
STATUS_TRIALING = "trialing"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

# Statuses that should currently unlock the plan's paid features.
ACTIVE_STATUSES = {STATUS_ACTIVE, STATUS_TRIALING}


class Subscription(Base):
    """
    A company's relationship to a Plan over time.

    One row per company (enforced at the application layer, not a unique
    constraint, so we can keep historical rows if we ever need to later -
    but v1 only ever creates/updates a single active row per company).
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)

    status = Column(String(20), nullable=False, default=STATUS_ACTIVE)

    # Which payment gateway this subscription is billed through, e.g. "payfast".
    # Null/"" for the free Starter plan, which never touches a payment gateway.
    payment_provider = Column(String(50), nullable=True)

    # Provider-side identifiers, used to correlate webhook events back to
    # this subscription and to avoid creating duplicate records.
    customer_id = Column(String(150), nullable=True)

    subscription_id = Column(String(150), nullable=True, index=True)

    current_period_start = Column(DateTime(timezone=True), nullable=True)

    current_period_end = Column(DateTime(timezone=True), nullable=True)

    # If true, the subscription remains active until current_period_end,
    # then reverts to Starter instead of renewing.
    cancel_at_period_end = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    plan = relationship("Plan", back_populates="subscriptions")

    company = relationship("Company", back_populates="subscription")

    payments = relationship(
        "Payment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )
