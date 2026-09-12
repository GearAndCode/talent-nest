import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.candidate import Candidate
from app.schemas.ranking import RankedCandidate
from app.schemas.application import ApplicationCreate, ApplicationResponse, ApplicationUpdate
from app.services.semantic_matcher import calculate_semantic_match
from app.services.ollama_service import analyze_candidate
from app.services.embedding_service import get_embedding
from app.auth.oauth2 import get_current_identity, get_current_candidate, get_current_company
from app.auth.plan_access import enforce_application_limit, require_feature
from app.services import subscription_service

logger = logging.getLogger("talentnest.routers.application")

router = APIRouter(prefix="/applications", tags=["Applications"])

# Fallback AI-recruiter-analysis payload used whenever the Ollama analysis
# step is unavailable (e.g. no local Ollama model server reachable from the
# deployed backend). Applying for a job must never depend on this optional
# AI service being up.
_ANALYSIS_FALLBACK = {
    "matched_skills": [],
    "missing_skills": [],
    "recommendation": "AI recommendation not available yet.",
    "overall_summary": "AI analysis is temporarily unavailable for this application.",
    "interview_questions": [],
}


@router.post("/", response_model=ApplicationResponse)
def apply_for_job(
    application: ApplicationCreate,
    db: Session = Depends(get_db),
    candidate=Depends(get_current_candidate),
):
    # Never trust candidate_id from the browser.
    candidate_id = candidate.id
    logger.info(f"POST /applications/ reached - candidate_id={candidate_id} job_id={application.job_id}")

    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        logger.info(f"Job {application.job_id} not found for application by candidate {candidate_id}")
        raise HTTPException(status_code=404, detail="Job not found.")

    if not candidate.resume_text:
        raise HTTPException(status_code=400, detail="Please upload your resume before applying.")

    existing = db.query(Application).filter(
        Application.candidate_id == candidate_id,
        Application.job_id == application.job_id,
    ).first()
    if existing:
        logger.info(f"Duplicate application blocked - candidate_id={candidate_id} job_id={job.id}")
        raise HTTPException(status_code=400, detail="Already applied.")

    if not candidate.embedding:
        raise HTTPException(status_code=400, detail="Candidate embedding not found. Upload the resume again.")

    # Enforce the hiring company's plan limit on applications-per-job.
    # Server-side, so it can't be bypassed regardless of what the frontend
    # shows the candidate.
    existing_application_count = (
        db.query(Application).filter(Application.job_id == job.id).count()
    )
    enforce_application_limit(db, job.company, existing_application_count)

    # ------------------------------------------------------------------
    # OPTIONAL: job embedding (used only for AI match scoring/ranking).
    #
    # Jobs created before embedding generation existed (or any job whose
    # embedding failed to persist) can have a NULL embedding column. We
    # opportunistically (re)generate it here using the job's real
    # description so future AI matching/ranking has real data to work
    # with. But this is a "nice to have" for search/ranking, not a
    # requirement for the application itself to be saved - so a failure
    # here (e.g. missing/invalid OPENAI_API_KEY, quota, network egress
    # blocked on Render) must NOT block the candidate from applying.
    # ------------------------------------------------------------------
    if not job.embedding:
        try:
            job.embedding = json.dumps(get_embedding(job.description))
            db.commit()
            db.refresh(job)
            logger.info(f"Generated job embedding for job {job.id}")
        except Exception as exc:
            db.rollback()
            # Logged so the real cause (missing/invalid OPENAI_API_KEY,
            # quota, network egress, etc.) is visible in the Render logs,
            # instead of turning into a 503 that blocks the applicant.
            logger.error(f"EMBEDDING GENERATION FAILED for job {job.id}: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # OPTIONAL: AI semantic match score (candidate embedding vs job
    # embedding). Only possible once both embeddings exist. If the job
    # embedding above failed/was skipped, fall back to a neutral score
    # rather than blocking the application.
    # ------------------------------------------------------------------
    if job.embedding:
        try:
            ai_result = calculate_semantic_match(
                json.loads(candidate.embedding),
                json.loads(job.embedding),
            )
        except Exception as exc:
            logger.error(f"SEMANTIC MATCH CALCULATION FAILED for job {job.id}: {type(exc).__name__}: {exc}")
            ai_result = {"score": 0, "recommendation": "Not available"}
    else:
        logger.info(f"Skipping semantic match for job {job.id} - no job embedding available")
        ai_result = {"score": 0, "recommendation": "Not available"}

    # ------------------------------------------------------------------
    # OPTIONAL: AI recruiter analysis (Ollama). Requires a reachable
    # Ollama model server, which will typically NOT be available from the
    # deployed backend. A failure here must never prevent the application
    # from being saved - fall back to a neutral analysis payload instead.
    # ------------------------------------------------------------------
    try:
        analysis = analyze_candidate(candidate.resume_text, job.description)
    except Exception as exc:
        logger.error(f"AI RECRUITER ANALYSIS FAILED for job {job.id} / candidate {candidate_id}: {type(exc).__name__}: {exc}")
        analysis = _ANALYSIS_FALLBACK

    try:
        new_application = Application(
            candidate_id=candidate_id,
            job_id=job.id,
            status="Applied",
            match_score=ai_result.get("score", 0),
            matched_skills=", ".join(analysis.get("matched_skills", [])),
            missing_skills=", ".join(analysis.get("missing_skills", [])),
            ai_recommendation=analysis.get("recommendation", ""),
            ai_summary=analysis.get("overall_summary", ""),
            interview_questions=analysis.get("interview_questions", []),
        )
        db.add(new_application)
        db.commit()
        db.refresh(new_application)
    except Exception as exc:
        db.rollback()
        logger.error(f"APPLICATION DB COMMIT FAILED for candidate {candidate_id} / job {job.id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Your application could not be saved right now. Please try again.",
        )

    logger.info(f"Application {new_application.id} created - candidate_id={candidate_id} job_id={job.id}")
    return new_application


def _mask_ai_fields_if_unentitled(applications: list[Application], db: Session, company_id: int) -> list[Application]:
    """
    AI resume analysis (matched_skills, missing_skills, ai_recommendation,
    ai_summary, interview_questions) and the AI match score/ranking are
    computed automatically for every application at apply-time, regardless
    of the hiring company's plan - that computation is cheap and
    candidate-facing behavior shouldn't depend on the employer's billing.
    What must be gated is whether the HR user is allowed to SEE those AI
    results (several HR pages, e.g. AI Rankings, derive rankings straight
    from this list rather than calling a separate endpoint, so masking
    must happen here too, not only on the dedicated ranking endpoint).

    Starter companies get the raw application (status, candidate) with AI
    fields blanked out and match_score zeroed; Professional/Business see
    everything.
    """
    subscription = subscription_service.get_or_create_subscription(db, company_id)
    has_resume_analysis = subscription_service.has_feature(subscription, "ai_resume_analysis_enabled")
    has_ranking = subscription_service.has_feature(subscription, "ai_candidate_ranking_enabled")

    if has_resume_analysis and has_ranking:
        return applications

    for app in applications:
        if not has_resume_analysis:
            app.matched_skills = None
            app.missing_skills = None
            app.ai_recommendation = None
            app.ai_summary = None
            app.interview_questions = None
        if not has_ranking:
            app.match_score = 0

    return applications


@router.get("/", response_model=list[ApplicationResponse])
def get_applications(
    identity=Depends(get_current_identity),
    db: Session = Depends(get_db),
):
    if identity["type"] == "candidate":
        return db.query(Application).filter(
            Application.candidate_id == identity["candidate_id"]
        ).all()

    company_id = identity["company_id"]
    applications = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company_id)
        .all()
    )
    return _mask_ai_fields_if_unentitled(applications, db, company_id)


@router.get("/jobs/{job_id}/ranked-candidates", response_model=list[RankedCandidate])
def ranked_candidates(
    job_id: int,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
    subscription=Depends(require_feature("ai_candidate_ranking_enabled")),
):
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.company_id == company.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found for your company.")

    applications = (
        db.query(Application)
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
    subscription=Depends(require_feature("advanced_analytics_enabled")),
):
    applications = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company.id)
        .all()
    )
    return [
        {"candidate": app.candidate.full_name, "score": app.match_score}
        for app in applications
    ]


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

    if identity["type"] == "company":
        _mask_ai_fields_if_unentitled([application], db, identity["company_id"])

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
