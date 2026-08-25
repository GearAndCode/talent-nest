"""
Background AI-analysis pipeline for applications.

This module is intentionally decoupled from the request/response cycle of
the `/applications/` endpoint. It is invoked via FastAPI `BackgroundTasks`
*after* the HTTP response for a new application has already been returned
to the candidate, so nothing here can make the candidate wait.

Design constraints (see the application-submission performance fix):
  * Uses its own SQLAlchemy session - the request's session is closed by
    the time this runs, so reusing it would be unsafe.
  * Every external call (OpenAI embeddings, Ollama) is wrapped so a
    failure here can NEVER change `application.status` away from
    "Applied". Only `analysis_status` reflects AI outcomes.
  * The Ollama call has a hard timeout + a single retry, then FAILED.
  * No resume/job text is logged - only ids and timings.
"""

import concurrent.futures
import json
import logging
import time
from typing import Any, Dict

from app.database import SessionLocal
from app.models.application import Application
from app.models.job import Job
from app.models.candidate import Candidate
from app.services.embedding_service import get_embedding
from app.services.semantic_matcher import calculate_semantic_match
from app.services.ollama_service import analyze_candidate

logger = logging.getLogger("talentnest.services.analysis_worker")

# Hard ceiling per Ollama attempt. If the model server hangs (e.g. cold
# start, overloaded box, network partition) this guarantees the background
# job eventually gives up instead of running forever.
OLLAMA_TIMEOUT_SECONDS = 120
OLLAMA_MAX_ATTEMPTS = 2

_ANALYSIS_FALLBACK: Dict[str, Any] = {
    "matched_skills": [],
    "missing_skills": [],
    "recommendation": "AI recommendation not available yet.",
    "overall_summary": "AI analysis is temporarily unavailable for this application.",
    "interview_questions": [],
}


def _run_ollama_with_timeout(resume_text: str, job_description: str) -> Dict[str, Any]:
    """Runs analyze_candidate with a bounded timeout and one retry.

    Raises the last exception if every attempt fails/hangs, so the caller
    can record a FAILED analysis_status.
    """
    last_exc: Exception | None = None

    for attempt in range(1, OLLAMA_MAX_ATTEMPTS + 1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(analyze_candidate, resume_text, job_description)
            try:
                return future.result(timeout=OLLAMA_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError as exc:
                last_exc = exc
                logger.error(
                    "Ollama analysis attempt %s/%s timed out after %ss",
                    attempt, OLLAMA_MAX_ATTEMPTS, OLLAMA_TIMEOUT_SECONDS,
                )
                # The underlying thread may still be running; we simply stop
                # waiting on it and let the executor context manager tear
                # down. We do not block application processing on it.
            except Exception as exc:  # noqa: BLE001 - genuinely want to catch/log everything here
                last_exc = exc
                logger.error(
                    "Ollama analysis attempt %s/%s failed: %s: %s",
                    attempt, OLLAMA_MAX_ATTEMPTS, type(exc).__name__, exc,
                )

    raise last_exc if last_exc else RuntimeError("Ollama analysis failed for an unknown reason")


def process_application_analysis(application_id: int) -> None:
    """Entry point invoked from FastAPI BackgroundTasks.

    Must never raise - this runs detached from any request, so an
    uncaught exception here would just be swallowed by the background
    task runner and leave the application stuck on PROCESSING. Every
    stage is wrapped individually.
    """
    overall_start = time.perf_counter()
    db = SessionLocal()

    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            logger.error("process_application_analysis: application %s not found", application_id)
            return

        application.analysis_status = "PROCESSING"
        db.commit()

        job = db.query(Job).filter(Job.id == application.job_id).first()
        candidate = db.query(Candidate).filter(Candidate.id == application.candidate_id).first()

        if not job or not candidate:
            logger.error(
                "process_application_analysis: missing job=%s or candidate=%s for application=%s",
                application.job_id, application.candidate_id, application_id,
            )
            application.analysis_status = "FAILED"
            application.analysis_error = "Job or candidate record no longer exists."
            db.commit()
            return

        # ------------------------------------------------------------
        # Stage 1: job embedding (only if not already cached on the job).
        # ------------------------------------------------------------
        stage_start = time.perf_counter()
        if not job.embedding:
            try:
                job.embedding = json.dumps(get_embedding(job.description))
                db.commit()
                db.refresh(job)
            except Exception as exc:
                db.rollback()
                logger.error(
                    "job embedding generation FAILED for job=%s: %s: %s",
                    job.id, type(exc).__name__, exc,
                )
        embedding_ms = (time.perf_counter() - stage_start) * 1000

        # ------------------------------------------------------------
        # Stage 2: semantic match score.
        # ------------------------------------------------------------
        stage_start = time.perf_counter()
        if job.embedding and candidate.embedding:
            try:
                ai_result = calculate_semantic_match(
                    json.loads(candidate.embedding),
                    json.loads(job.embedding),
                )
            except Exception as exc:
                logger.error(
                    "semantic match FAILED for application=%s: %s: %s",
                    application_id, type(exc).__name__, exc,
                )
                ai_result = {"score": 0, "recommendation": "Not available"}
        else:
            ai_result = {"score": 0, "recommendation": "Not available"}
        matching_ms = (time.perf_counter() - stage_start) * 1000

        # ------------------------------------------------------------
        # Stage 3: Ollama recruiter analysis (the expensive part).
        # ------------------------------------------------------------
        stage_start = time.perf_counter()
        analysis_failed = False
        analysis_error_message = None
        try:
            analysis = _run_ollama_with_timeout(candidate.resume_text or "", job.description or "")
        except Exception as exc:
            logger.error(
                "AI recruiter analysis FAILED for application=%s: %s: %s",
                application_id, type(exc).__name__, exc,
            )
            analysis = _ANALYSIS_FALLBACK
            analysis_failed = True
            analysis_error_message = f"{type(exc).__name__}: {exc}"[:500]
        ollama_ms = (time.perf_counter() - stage_start) * 1000

        # ------------------------------------------------------------
        # Stage 4: persist results. The application row already exists -
        # this is an UPDATE only, never touches application.status.
        # ------------------------------------------------------------
        application.match_score = ai_result.get("score", 0)
        application.matched_skills = ", ".join(analysis.get("matched_skills", []))
        application.missing_skills = ", ".join(analysis.get("missing_skills", []))
        application.ai_recommendation = analysis.get("recommendation", "")
        application.ai_summary = analysis.get("overall_summary", "")
        application.interview_questions = analysis.get("interview_questions", [])
        application.analysis_status = "FAILED" if analysis_failed else "COMPLETED"
        application.analysis_error = analysis_error_message
        db.commit()

        total_ms = (time.perf_counter() - overall_start) * 1000
        logger.info(
            "Background analysis finished application_id=%s status=%s "
            "embedding_ms=%.2f matching_ms=%.2f ollama_ms=%.2f total_ms=%.2f",
            application_id, application.analysis_status,
            embedding_ms, matching_ms, ollama_ms, total_ms,
        )

    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        db.rollback()
        logger.error(
            "process_application_analysis crashed for application=%s: %s: %s",
            application_id, type(exc).__name__, exc,
        )
        try:
            application = db.query(Application).filter(Application.id == application_id).first()
            if application:
                application.analysis_status = "FAILED"
                application.analysis_error = f"{type(exc).__name__}: {exc}"[:500]
                db.commit()
        except Exception:
            db.rollback()
            logger.error("process_application_analysis: could not even record FAILED status for application=%s", application_id)
    finally:
        db.close()
