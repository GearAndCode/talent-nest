import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.candidate import Candidate
from app.schemas.ranking import RankedCandidate
from app.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationStatusResponse,
    ApplicationUpdate,
)
from app.auth.oauth2 import get_current_identity, get_current_candidate, get_current_company
from app.services.analysis_worker import process_application_analysis

logger = logging.getLogger("talentnest.routers.application")

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("/", response_model=ApplicationResponse)
def apply_for_job(
    application: ApplicationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    candidate=Depends(get_current_candidate),
):
    """
    Creates the application record and returns immediately.

    IMPORTANT: This endpoint must stay fast (target: well under 3 seconds).
    It performs only cheap, synchronous validation + a single DB write.
    All AI work (embeddings, semantic matching, Ollama recruiter analysis)
    happens afterwards in a background task - see
    app.services.analysis_worker.process_application_analysis. A candidate
    must never wait on Ollama (or any other AI step) to submit an
    application, and the application must remain "Applied" even if AI
    analysis later fails.
    """
    request_start = time.perf_counter()

    # Never trust candidate_id from the browser.
    candidate_id = candidate.id
    logger.info(f"POST /applications/ reached - candidate_id={candidate_id} job_id={application.job_id}")

    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        logger.info(f"Job {application.job_id} not found for application by candidate {candidate_id}")
        raise HTTPException(status_code=404, detail="Job not found.")

    if not candidate.resume_text:
        raise HTTPException(status_code=400, detail="Please upload your resume before applying.")

    if not candidate.embedding:
        raise HTTPException(status_code=400, detail="Candidate embedding not found. Upload the resume again.")

    existing = db.query(Application).filter(
        Application.candidate_id == candidate_id,
        Application.job_id == application.job_id,
    ).first()
    if existing:
        logger.info(f"Duplicate application blocked - candidate_id={candidate_id} job_id={job.id}")
        raise HTTPException(status_code=400, detail="Already applied.")

    validation_ms = (time.perf_counter() - request_start) * 1000

    # ------------------------------------------------------------------
    # Create + commit the application record. This is the ONLY database
    # write the candidate has to wait for. No AI calls happen above this
    # line or below it, before the response is returned.
    # ------------------------------------------------------------------
    new_application = Application(
        candidate_id=candidate_id,
        job_id=job.id,
        status="Applied",
        analysis_status="PENDING",
    )
    db.add(new_application)
    try:
        db.commit()
        db.refresh(new_application)
    except IntegrityError:
        # A concurrent request for the same candidate+job pair beat us to
        # the DB-level unique constraint - this is the expected/safe
        # outcome under a race, not a real server error.
        db.rollback()
        logger.info(f"Duplicate application race caught by DB constraint - candidate_id={candidate_id} job_id={job.id}")
        raise HTTPException(status_code=400, detail="Already applied.")
    except Exception as exc:
        db.rollback()
        logger.error(f"APPLICATION DB COMMIT FAILED for candidate {candidate_id} / job {job.id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Your application could not be saved right now. Please try again.",
        )

    total_ms = (time.perf_counter() - request_start) * 1000
    logger.info(
        "Application %s created - candidate_id=%s job_id=%s validation_ms=%.2f total_ms=%.2f",
        new_application.id, candidate_id, job.id, validation_ms, total_ms,
    )

    # Kick off AI analysis AFTER the transaction is committed and the
    # response is on its way back to the candidate. FastAPI runs
    # BackgroundTasks in a worker thread after the response has been sent,
    # so this line does not add any latency to the request.
    background_tasks.add_task(process_application_analysis, new_application.id)

    return new_application


@router.get("/", response_model=list[ApplicationResponse])
def get_applications(
    identity=Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    if identity["type"] == "candidate":
        return (
            db.query(Application)
            .filter(Application.candidate_id == identity["candidate_id"])
            .all()
        )

    company_id = identity["company_id"]
    return (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company_id)
        .all()
    )


@router.get("/jobs/{job_id}/ranked-candidates", response_model=list[RankedCandidate])
def ranked_candidates(
    job_id: int,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.company_id == company.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found for your company.")

    applications = (
        db.query(Application)
        .options(joinedload(Application.candidate))
        .filter(Application.job_id == job_id)
        .order_by(Application.match_score.desc())
        .all()
    )

    return [
        RankedCandidate(
            candidate_id=app.candidate.id,
            candidate_name=app.candidate.full_name,
            match_score=app.match_score or 0,
            recommendation=app.ai_recommendation or "No recommendation available",
        )
        for app in applications
    ]


@router.get("/match-distribution")
def match_distribution(
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    applications = (
        db.query(Application)
        .options(joinedload(Application.candidate))
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company.id)
        .all()
    )
    return [
        {"candidate": app.candidate.full_name, "score": app.match_score}
        for app in applications
    ]


@router.get("/{application_id}/status", response_model=ApplicationStatusResponse)
def get_application_status(
    application_id: int,
    identity=Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    """Lightweight endpoint for the frontend to poll AI-analysis progress
    (PENDING -> PROCESSING -> COMPLETED/FAILED) without re-fetching the
    full application payload."""
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")

    if identity["type"] == "candidate":
        allowed = application.candidate_id == identity["candidate_id"]
    else:
        allowed = application.job.company_id == identity["company_id"]

    if not allowed:
        raise HTTPException(status_code=404, detail="Application not found.")

    return ApplicationStatusResponse(
        application_id=application.id,
        application_status=application.status,
        analysis_status=application.analysis_status,
        match_score=application.match_score,
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    identity=Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")

    if identity["type"] == "candidate":
        allowed = application.candidate_id == identity["candidate_id"]
    else:
        allowed = application.job.company_id == identity["company_id"]

    if not allowed:
        raise HTTPException(status_code=404, detail="Application not found.")

    return application


@router.put("/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: int,
    updated: ApplicationUpdate,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    application = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.id == application_id,
            Job.company_id == company.id,
        )
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found for your company.")

    application.status = updated.status
    db.commit()
    db.refresh(application)
    return application


@router.delete("/{application_id}")
def delete_application(
    application_id: int,
    identity=Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")

    if identity["type"] == "candidate":
        allowed = application.candidate_id == identity["candidate_id"]
    else:
        allowed = application.job.company_id == identity["company_id"]

    if not allowed:
        raise HTTPException(status_code=404, detail="Application not found.")

    db.delete(application)
    db.commit()
    return {"message": "Application deleted successfully"}
