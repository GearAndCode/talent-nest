from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    DateTime,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        # Application-level duplicate checking alone is not safe under
        # concurrent requests - enforce it at the database level too.
        UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
        Index("ix_applications_job_id_status", "job_id", "status"),
        Index("ix_applications_candidate_id_status", "candidate_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        index=True,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        index=True,
    )

    status = Column(
        String(50),
        default="Applied"
    )

    applied_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    # ---------------- AI Analysis lifecycle ----------------
    # PENDING -> the application was just created; AI work hasn't started.
    # PROCESSING -> the background job has picked it up and is running.
    # COMPLETED -> AI analysis finished and the fields below are populated.
    # FAILED -> AI analysis could not complete (Ollama down, timeout, bad
    #           output, etc). The application itself remains "Applied"
    #           regardless of this value.
    analysis_status = Column(
        String(20),
        default="PENDING",
        server_default="PENDING",
        nullable=False,
        index=True,
    )

    analysis_error = Column(Text)

    # ---------------- AI Matching ----------------

    match_score = Column(Integer, nullable=True)

    matched_skills = Column(Text)

    missing_skills = Column(Text)

    ai_recommendation = Column(Text)

    # ---------------- AI Recruiter Analysis ----------------

    ai_summary = Column(Text)

    interview_questions = Column(JSON)

    # -------------------------------------------------------

    candidate = relationship(
        "Candidate",
        back_populates="applications"
    )

    job = relationship(
        "Job",
        back_populates="applications"
    )