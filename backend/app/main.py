import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.database import engine
from app.models.company import Base

# Import models so SQLAlchemy creates all tables
from app.models import company, job, candidate, application, subscriber

from app.routers.candidate_auth import router as candidate_auth_router

# Import routers
from app.routers.auth import router as auth_router
from app.routers.jobs import router as jobs_router
from app.routers.candidate import router as candidate_router
from app.routers.application import router as application_router
from app.routers.dashboard import router as dashboard_router
from app.routers.subscriber import router as subscriber_router
from app.routers.hr_access_router import router as hr_access_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("talentnest.main")


# Create database tables (only creates tables that don't exist yet).
Base.metadata.create_all(bind=engine)


def _ensure_job_background_processing_columns() -> None:
    """Lightweight, idempotent schema patch.

    This project has no Alembic migrations wired up, and
    `Base.metadata.create_all()` above only creates missing TABLES, not
    missing COLUMNS on tables that already exist. The job-creation
    performance fix added a few new columns to `jobs` (status,
    processing_status, processing_error, description_hash), so on an
    existing database they need to be added explicitly. Safe to run on
    every startup - it only adds a column if it isn't already there.
    """
    inspector = inspect(engine)

    if "jobs" not in inspector.get_table_names():
        return  # create_all() will have just created it with all columns.

    existing_columns = {col["name"] for col in inspector.get_columns("jobs")}

    statements = []
    if "status" not in existing_columns:
        statements.append(
            "ALTER TABLE jobs ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'"
        )
    if "processing_status" not in existing_columns:
        statements.append(
            "ALTER TABLE jobs ADD COLUMN processing_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'"
        )
    if "processing_error" not in existing_columns:
        statements.append("ALTER TABLE jobs ADD COLUMN processing_error TEXT")
    if "description_hash" not in existing_columns:
        statements.append("ALTER TABLE jobs ADD COLUMN description_hash VARCHAR(64)")

    if not statements:
        return

    with engine.begin() as conn:
        for statement in statements:
            logger.info("schema_patch executing: %s", statement)
            conn.execute(text(statement))


_ensure_job_background_processing_columns()

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


@app.get("/")
def root():
    return {
        "status": "success",
        "message": "TalentNest Backend Running 🚀",
    }
