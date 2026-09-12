from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import validate_payment_config
from app.database import engine
from app.models.company import Base
from app.startup_migrations import run_payment_migrations

# Import models so SQLAlchemy creates all tables
from app.models import company, job, candidate, application, subscriber, plan, subscription, payment

from app.routers.candidate_auth import router as candidate_auth_router

# Import routers
from app.routers.auth import router as auth_router
from app.routers.jobs import router as jobs_router
from app.routers.candidate import router as candidate_router
from app.routers.application import router as application_router
from app.routers.dashboard import router as dashboard_router
from app.routers.subscriber import router as subscriber_router
from app.routers.hr_access_router import router as hr_access_router
from app.routers.subscription import router as subscription_router

from app.database import SessionLocal
from app.services.subscription_service import ensure_plans_seeded


# Fail fast if this is a production process without valid PayFast config,
# instead of starting up and only discovering it at checkout/webhook time.
validate_payment_config()

# Create database tables
Base.metadata.create_all(bind=engine)

# create_all() only creates brand-new tables; it never adds a column to a
# payments table that already exists from before the renewal feature. This
# additive, idempotent migration adds `is_renewal` on every boot instead.
run_payment_migrations(engine)

# Seed/refresh the three plan rows (Starter/Professional/Business) on
# startup so /plans always has data, even on a fresh database.
_db = SessionLocal()
try:
    ensure_plans_seeded(_db)
finally:
    _db.close()

app = FastAPI(
    title="TalentNest ATS Backend",
    version="1.0.0",
)


# Serve uploaded files (resumes)
app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads",
)


# CORS
# Production frontend is hosted on Vercel and the backend on Render.
# Using "*" here allows Vercel preview/production deployments to call
# the backend without the changing Vercel deployment URL causing CORS errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers
app.include_router(auth_router)
app.include_router(candidate_auth_router)
app.include_router(jobs_router)
app.include_router(candidate_router)
app.include_router(application_router)
app.include_router(dashboard_router)
app.include_router(subscriber_router)
app.include_router(hr_access_router)
app.include_router(subscription_router)


@app.get("/")
def root():
    return {
        "status": "success",
        "message": "TalentNest Backend Running 🚀",
    }
