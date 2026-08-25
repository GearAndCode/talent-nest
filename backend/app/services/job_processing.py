"""
Background processing for jobs.

This module contains everything that is allowed to be SLOW (OpenAI
embeddings today; extend here for requirement extraction / semantic
indexing later). None of it may ever run on the request path for
POST/PUT /jobs - it is only ever invoked via FastAPI BackgroundTasks
(see app/routers/jobs.py) AFTER the job row has already been committed
and the HTTP response has already been sent to the HR user.

Each background call gets its OWN database session (SessionLocal()),
never the request-scoped session from `get_db`, because that session is
closed the moment the request finishes.
"""

import json
import logging
import time

from app.database import SessionLocal
from app.models.job import Job
from app.services.embedding_service import get_embedding
from app.utils.hashing import content_hash

logger = logging.getLogger("talentnest.services.job_processing")


def process_job_background(job_id: int, description: str) -> None:
    """Generate/refresh a job's embedding in the background.

    Never raises - any failure is recorded on the job as
    processing_status=FAILED (+ processing_error) and swallowed, so a
    crashed/unreachable embedding provider can never affect the job
    record itself (job.status is untouched here).
    """
    db = SessionLocal()
    start = time.perf_counter()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning("job_processing skipped: job_id=%s no longer exists", job_id)
            return

        job.processing_status = "PROCESSING"
        db.commit()

        embed_start = time.perf_counter()
        embedding = get_embedding(description)
        embed_ms = (time.perf_counter() - embed_start) * 1000
        logger.info("job_processing step=embedding job_id=%s elapsed_ms=%.2f", job_id, embed_ms)

        job.embedding = json.dumps(embedding)
        job.description_hash = content_hash(description)
        job.processing_status = "COMPLETED"
        job.processing_error = None
        db.commit()

        total_ms = (time.perf_counter() - start) * 1000
        logger.info("job_processing step=total job_id=%s status=COMPLETED elapsed_ms=%.2f", job_id, total_ms)

    except Exception as exc:
        db.rollback()
        logger.error(
            "job_processing FAILED job_id=%s error_type=%s error=%s",
            job_id, type(exc).__name__, exc,
        )
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                # AI failure must never delete/rollback the job itself -
                # only the enrichment status is marked FAILED.
                job.processing_status = "FAILED"
                job.processing_error = f"{type(exc).__name__}: {exc}"[:2000]
                db.commit()
        except Exception as inner_exc:
            db.rollback()
            logger.error(
                "job_processing: failed to record FAILED status job_id=%s error=%s",
                job_id, inner_exc,
            )
    finally:
        db.close()
