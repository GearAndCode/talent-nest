from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.company import Company
from app.models.job import Job
from app.models.candidate import Candidate
from app.models.application import Application
from app.auth.oauth2 import get_current_company
from app.services import subscription_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
def get_dashboard_stats(
    company=Depends(get_current_company),
    db: Session = Depends(get_db),
):
    company_jobs = db.query(Job).filter(Job.company_id == company.id)

    total_jobs = company_jobs.count()

    company_applications = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company.id)
    )

    total_applications = company_applications.count()

    total_candidates = (
        db.query(Candidate)
        .join(Application, Application.candidate_id == Candidate.id)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == company.id)
        .distinct()
        .count()
    )

    base_stats = {
        "company_id": company.id,
        "company_name": company.company_name,
        "jobs": total_jobs,
        "candidates": total_candidates,
        "applications": total_applications,
    }

    # AI-derived aggregates (match scores, "recommended for interview" count)
    # are only computed off the same AI resume analysis / candidate ranking
    # data gated everywhere else. A Starter company must not receive real
    # numbers here just because it's a different endpoint - that would leak
    # paid-feature output. Return an explicit locked marker instead of 0s,
    # so the frontend can render an upgrade prompt rather than a fake stat.
    subscription = subscription_service.get_or_create_subscription(db, company.id)
    has_ai_insights = subscription_service.has_feature(
        subscription, "ai_resume_analysis_enabled"
    ) and subscription_service.has_feature(subscription, "ai_candidate_ranking_enabled")

    if not has_ai_insights:
        base_stats["ai_insights_locked"] = True
        base_stats["average_match_score"] = None
        base_stats["highest_match_score"] = None
        base_stats["lowest_match_score"] = None
        base_stats["recommended_for_interview"] = None
        return base_stats

    average_match_score = company_applications.with_entities(
        func.avg(Application.match_score)
    ).scalar()

    highest_match_score = company_applications.with_entities(
        func.max(Application.match_score)
    ).scalar()

    lowest_match_score = company_applications.with_entities(
        func.min(Application.match_score)
    ).scalar()

    recommended_for_interview = company_applications.filter(
        Application.ai_recommendation.ilike("%recommend%")
    ).count()

    base_stats["ai_insights_locked"] = False
    base_stats["average_match_score"] = round(average_match_score or 0, 2)
    base_stats["highest_match_score"] = highest_match_score or 0
    base_stats["lowest_match_score"] = lowest_match_score or 0
    base_stats["recommended_for_interview"] = recommended_for_interview
    return base_stats
