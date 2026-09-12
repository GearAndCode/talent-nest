from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Plan(Base):
    """
    A purchasable TalentNest subscription tier (Starter / Professional / Business).

    Plans are the single source of truth for pricing, limits, and which
    premium features a company can use. They are seeded once at startup
    (see app.services.subscription_service.ensure_plans_seeded) and can be
    safely re-read by both the pricing page and the backend authorization
    layer, so the two never drift apart.
    """

    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)

    # Stable machine-readable key used in code/config, e.g. "starter".
    code = Column(String(50), unique=True, nullable=False, index=True)

    name = Column(String(100), nullable=False)

    price = Column(Numeric(10, 2), nullable=False, default=0)

    currency = Column(String(10), nullable=False, default="USD")

    billing_interval = Column(String(20), nullable=False, default="month")

    is_most_popular = Column(Boolean, default=False)

    # ---------------- Usage limits ----------------

    max_active_jobs = Column(Integer, nullable=False, default=1)

    max_applications_per_job = Column(Integer, nullable=False, default=25)

    max_recruiters = Column(Integer, nullable=False, default=1)

    # ---------------- Feature flags ----------------

    ai_resume_analysis_enabled = Column(Boolean, default=False)

    ai_candidate_ranking_enabled = Column(Boolean, default=False)

    ai_recommendations_enabled = Column(Boolean, default=False)

    ai_interview_questions_enabled = Column(Boolean, default=False)

    advanced_analytics_enabled = Column(Boolean, default=False)

    multiple_recruiters_enabled = Column(Boolean, default=False)

    display_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    subscriptions = relationship("Subscription", back_populates="plan")
