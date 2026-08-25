import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from fastapi.security import OAuth2PasswordBearer

from app.database import SessionLocal, get_db
from app.models.job import Job
from app.models.company import Company
from app.models.subscriber import Subscriber
from app.schemas.job import JobCreate, JobProcessingStatus, JobResponse
from app.services.job_processing import process_job_background
from app.services.email_service import send_new_job_alerts
from app.utils.hashing import content_hash
from app.auth.oauth2 import get_current_company

logger = logging.getLogger("talentnest.routers.jobs")

router = APIRouter(prefix="/jobs", tags=["Jobs"])

optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False,
)


def _parse_job_skills(job: Job) -> Job:
    if isinstance(job.skills, str):
        try:
            job.skills = json.loads(job.skills)
        except Exception:
            job.skills = []
    elif job.skills is None:
        job.skills = []
    return job


def _job_response(job: Job) -> dict:
    """Build a job payload using the real Job -> Company relationship."""
    _parse_job_skills(job)
    company = job.company

    return {
        "id": job.id,
        "title": job.title,
        "department": job.department,
        "category": job.category,
        "location": job.location,
        "description": job.description,
        "salary": job.salary,
        "company_id": job.company_id,
        "company_name": company.company_name if company else "Unknown Company",
        "company_logo": company.logo if company else None,
        "company_headquarters": company.headquarters if company else None,
        "employment_type": job.employment_type,
        "experience": job.experience,
        "skills": job.skills,
        "created_at": job.created_at,
        "status": job.status,
        "processing_status": job.processing_status,
    }


def _send_job_alerts_background(job_id: int) -> None:
    """Send new-job alert emails to subscribers. Runs in the background,
    with its own DB session, well after the HTTP response has already
    gone back to the HR user - SMTP round-trips (up to 30s each,
    multiplied by every subscriber) must never sit on the request path.
    """
    db = SessionLocal()
    try:
        job = (
            db.query(Job)
            .options(joinedload(Job.company))
            .filter(Job.id == job_id)
            .first()
        )
        if not job:
            return

        subscribers = db.query(Subscriber).all()

        logger.info(
            "job_alerts start job_id=%s subscribers=%d", job_id, len(subscribers)
        )

        sent_count = send_new_job_alerts(subscribers, job, job.company)

        logger.info(
            "job_alerts done job_id=%s sent=%d/%d",
            job_id, sent_count, len(subscribers),
        )
    except Exception as exc:
        logger.error("job_alerts FAILED job_id=%s error=%s", job_id, exc)
    finally:
        db.close()


def _company_scope_query(query, token: Optional[str], db: Session):
    """Public/candidate requests see all jobs; company JWTs are tenant-scoped."""
    if not token:
        return query

    try:
        from app.auth.oauth2 import _decode_token

        payload = _decode_token(token)
        company_id = payload.get("company_id")

        if company_id is None:
            return query

        company_id = int(company_id)

        if not db.query(Company).filter(Company.id == company_id).first():
            raise HTTPException(
                status_code=401,
                detail="Company account not found.",
            )

        return query.filter(Job.company_id == company_id)

    except HTTPException:
        raise
    except Exception:
        return query


@router.post("/create", response_model=JobResponse)
def create_job(
    job: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    """Create + publish a job.

    Synchronous work here is intentionally limited to validation and the
    database write. AI embedding generation and job-alert emails are both
    slow, optional, and NOT required to create a job - they are scheduled
    as background tasks and run only after this response has already been
    sent back to the HR user.
    """
    request_start = time.perf_counter()

    # ------------------------------------------------------------------
    # Create + commit the job immediately. No AI/embedding work happens
    # before this point.
    # ------------------------------------------------------------------
    db_start = time.perf_counter()

    new_job = Job(
        company_id=company.id,
        title=job.title,
        department=job.department,
        category=job.category,
        location=job.location,
        description=job.description,
        salary=job.salary,
        employment_type=job.employment_type,
        experience=job.experience,
        skills=json.dumps(job.skills) if job.skills else "[]",
        embedding=None,
        status="ACTIVE",
        processing_status="PENDING",
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    db_ms = (time.perf_counter() - db_start) * 1000
    logger.info("job_creation step=database_commit job_id=%s elapsed_ms=%.2f", new_job.id, db_ms)

    # Reload with the actual company relationship for the response.
    new_job = (
        db.query(Job)
        .options(joinedload(Job.company))
        .filter(Job.id == new_job.id)
        .first()
    )

    # ------------------------------------------------------------------
    # Everything expensive/optional happens in the background from here.
    # Job creation is already done and committed - AI success/failure and
    # email delivery can no longer affect it.
    # ------------------------------------------------------------------
    background_tasks.add_task(process_job_background, new_job.id, new_job.description)
    background_tasks.add_task(_send_job_alerts_background, new_job.id)

    total_ms = (time.perf_counter() - request_start) * 1000
    logger.info("job_creation step=total job_id=%s elapsed_ms=%.2f", new_job.id, total_ms)

    return _job_response(new_job)


@router.get("/", response_model=list[JobResponse])
def get_jobs(
    token: Optional[str] = Depends(optional_oauth2),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Job)
        .options(joinedload(Job.company))
        .join(Company, Job.company_id == Company.id)
    )
    query = _company_scope_query(query, token, db)

    jobs = query.order_by(Job.created_at.desc()).all()
    return [_job_response(job) for job in jobs]


@router.get("/search", response_model=list[JobResponse])
def search_jobs(
    keyword: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    token: Optional[str] = Depends(optional_oauth2),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Job)
        .options(joinedload(Job.company))
        .join(Company, Job.company_id == Company.id)
    )
    query = _company_scope_query(query, token, db)

    if keyword and keyword.strip():
        value = keyword.strip()
        query = query.filter(
            or_(
                Job.title.ilike(f"%{value}%"),
                Job.description.ilike(f"%{value}%"),
                Job.category.ilike(f"%{value}%"),
                Job.skills.ilike(f"%{value}%"),
            )
        )

    if location and location.strip():
        query = query.filter(Job.location.ilike(f"%{location.strip()}%"))

    if department and department.strip():
        query = query.filter(Job.department.ilike(f"%{department.strip()}%"))

    jobs = query.order_by(Job.created_at.desc()).all()
    return [_job_response(job) for job in jobs]


@router.get("/{job_id}/processing-status", response_model=JobProcessingStatus)
def get_job_processing_status(
    job_id: int,
    db: Session = Depends(get_db),
):
    """Poll this to see whether background AI enrichment for a job has
    finished. The job itself is already created/ACTIVE regardless of what
    this returns."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return JobProcessingStatus(
        job_id=job.id,
        status=job.status,
        processing_status=job.processing_status,
        processing_error=job.processing_error,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    token: Optional[str] = Depends(optional_oauth2),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Job)
        .options(joinedload(Job.company))
        .join(Company, Job.company_id == Company.id)
        .filter(Job.id == job_id)
    )
    query = _company_scope_query(query, token, db)

    job = query.first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return _job_response(job)


@router.put("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: int,
    updated_job: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    request_start = time.perf_counter()

    job = db.query(Job).filter(
        Job.id == job_id,
        Job.company_id == company.id,
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found for your company.",
        )

    # Only re-run AI enrichment (embedding) if the description text
    # actually changed. Salary/location/deadline-only edits stay fast and
    # never touch the embedding.
    new_hash = content_hash(updated_job.description)
    description_changed = new_hash != job.description_hash

    job.title = updated_job.title
    job.department = updated_job.department
    job.category = updated_job.category
    job.location = updated_job.location
    job.description = updated_job.description
    job.salary = updated_job.salary
    job.employment_type = updated_job.employment_type
    job.experience = updated_job.experience
    job.skills = json.dumps(updated_job.skills) if updated_job.skills else "[]"

    if description_changed:
        job.processing_status = "PENDING"

    db.commit()
    db.refresh(job)

    job = (
        db.query(Job)
        .options(joinedload(Job.company))
        .filter(Job.id == job.id)
        .first()
    )

    if description_changed:
        background_tasks.add_task(process_job_background, job.id, job.description)
        logger.info("job_update job_id=%s description_changed=True -> reprocessing queued", job.id)
    else:
        logger.info("job_update job_id=%s description_changed=False -> AI reprocessing skipped", job.id)

    total_ms = (time.perf_counter() - request_start) * 1000
    logger.info("job_update step=total job_id=%s elapsed_ms=%.2f", job.id, total_ms)

    return _job_response(job)


@router.delete("/{job_id}")
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    company=Depends(get_current_company),
):
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.company_id == company.id,
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found for your company.",
        )

    db.delete(job)
    db.commit()

    return {"message": "Job deleted successfully"}
