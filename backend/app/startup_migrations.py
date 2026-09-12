"""
Small, idempotent, additive schema migrations.

`Base.metadata.create_all(bind=engine)` (used in app/main.py) only creates
tables that do not exist yet - it will NOT add new columns/indexes/
constraints to a table that is already present in the database. This
project has no Alembic migration pipeline wired into its runtime, so any
additive change to an existing table has to be applied here instead, in a
way that is safe to run every time the app starts.

Everything here uses "IF NOT EXISTS" / catches the specific "already
exists" error so re-running it on every boot is a no-op after the first
successful run.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("talentnest.startup_migrations")


def run_startup_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        # analysis_status / analysis_error: added so AI analysis can be
        # tracked independently of application.status (see the
        # application-submission performance fix).
        conn.execute(text(
            "ALTER TABLE applications "
            "ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'"
        ))
        conn.execute(text(
            "ALTER TABLE applications "
            "ADD COLUMN IF NOT EXISTS analysis_error TEXT"
        ))

        # Backfill: any pre-existing application that already has AI
        # fields populated (from the old synchronous flow) should read as
        # COMPLETED rather than the new-row default of PENDING.
        conn.execute(text(
            "UPDATE applications "
            "SET analysis_status = 'COMPLETED' "
            "WHERE analysis_status = 'PENDING' AND ai_summary IS NOT NULL AND ai_summary <> ''"
        ))

        # Helpful indexes for the query patterns this endpoint set uses.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_applications_job_id_status "
            "ON applications (job_id, status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_applications_candidate_id_status "
            "ON applications (candidate_id, status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_applications_analysis_status "
            "ON applications (analysis_status)"
        ))

    # The unique constraint has to be attempted separately: if duplicate
    # (candidate_id, job_id) rows already exist from before this fix, adding
    # it will fail. We don't want that to block application startup, so we
    # log and move on - the application-level duplicate check in the router
    # still protects non-concurrent requests.
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE applications "
                "ADD CONSTRAINT uq_applications_candidate_job UNIQUE (candidate_id, job_id)"
            ))
        logger.info("Added uq_applications_candidate_job unique constraint.")
    except Exception as exc:
        # Postgres error code 42P07 = duplicate_object (constraint already
        # exists) - expected on every boot after the first. Anything else
        # (e.g. existing duplicate rows) is logged so it can be cleaned up.
        message = str(exc)
        if "already exists" in message:
            pass
        else:
            logger.warning(
                "Could not add uq_applications_candidate_job unique constraint "
                "(likely duplicate candidate/job rows already exist - clean these "
                "up manually, then restart): %s",
                message,
            )


def run_payment_migrations(engine: Engine) -> None:
    """
    Additive migration for the recurring-payments/renewal feature.

    `is_renewal` distinguishes a renewal payment (extends the existing
    subscription period) from a first-time subscribe/upgrade payment
    (starts a fresh period) - see app.models.payment and
    app.services.subscription_service.renew_subscription. Existing rows
    default to false, i.e. "not a renewal", which is correct: every
    payment that predates this feature was a first-time subscribe or an
    upgrade.
    """
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE payments "
            "ADD COLUMN IF NOT EXISTS is_renewal BOOLEAN NOT NULL DEFAULT FALSE"
        ))
