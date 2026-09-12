"""
TalentNest subscription plan catalog.

This is the single source of truth for plan pricing, limits, and feature
lists. Both the public Plans page and (later) the checkout/payment
integration and any entitlement checks should read from here rather than
duplicating plan business data in the frontend or scattering it across
routers.

Each plan has a stable `id`. That id — not the display name and not the
price — is what the frontend sends when a user initiates checkout, and what
the backend will eventually store on a company's subscription record. This
keeps the identifier safe to reference even if the name or price changes.

There is intentionally no database model backing this yet: these values are
static product configuration, not per-user data. Once real billing/webhook
handling is introduced, this catalog is the natural place to look up plan
limits and to validate an incoming plan_id from the checkout flow.
"""

PLAN_CATALOG = [
    {
        "id": "starter",
        "name": "Starter",
        "tagline": "For teams just getting started with hiring.",
        "price_monthly": 0,
        "currency": "USD",
        "billing_period": "month",
        "active_jobs_limit": "1 active job",
        "applications_per_job_limit": "25 applications per job",
        "features": [
            "1 active job",
            "25 applications per job",
            "Basic dashboard",
            "Candidate management",
            "Application management",
            "Basic job management",
        ],
        "is_most_popular": False,
        "cta_label": "Get Started",
    },
    {
        "id": "professional",
        "name": "Professional",
        "tagline": "For growing teams that want AI-powered hiring.",
        "price_monthly": 9,
        "currency": "USD",
        "billing_period": "month",
        "active_jobs_limit": "5 active jobs",
        "applications_per_job_limit": "200 applications per job",
        "features": [
            "5 active jobs",
            "200 applications per job",
            "AI Resume Analysis",
            "AI Candidate Ranking",
            "AI Recommendations",
            "AI Interview Questions",
            "Advanced analytics",
            "Advanced candidate matching",
        ],
        "is_most_popular": True,
        "cta_label": "Subscribe",
    },
    {
        "id": "business",
        "name": "Business",
        "tagline": "For established teams hiring at scale.",
        "price_monthly": 19,
        "currency": "USD",
        "billing_period": "month",
        "active_jobs_limit": "15 active jobs",
        "applications_per_job_limit": "1,000 applications per job",
        "features": [
            "15 active jobs",
            "1,000 applications per job",
            "Everything in Professional",
            "Multiple recruiters / team accounts",
            "Advanced analytics",
            "Higher AI usage limits",
        ],
        "is_most_popular": False,
        "cta_label": "Subscribe",
    },
]


def get_plan_catalog():
    return PLAN_CATALOG


def get_plan_by_id(plan_id: str):
    return next((plan for plan in PLAN_CATALOG if plan["id"] == plan_id), None)
