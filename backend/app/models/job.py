from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False
    )

    title = Column(String(150), nullable=False)

    department = Column(String(100))

    category = Column(String(100))

    location = Column(String(100))

    description = Column(Text)

    salary = Column(Integer)

    employment_type = Column(String(50))

    experience = Column(String(100))

    skills = Column(Text)

    embedding = Column(Text)

    # ------------------------------------------------------------------
    # Background-processing bookkeeping.
    #
    # `status` (below) is the publish state of the job (e.g. ACTIVE) and
    # is set synchronously the moment the job is created - candidates can
    # see/apply to the job immediately. `processing_status` is a SEPARATE
    # concept: it only tracks the optional AI enrichment (embedding /
    # requirement extraction) that runs in the background afterwards.
    # A job is fully usable while processing_status is still PENDING or
    # PROCESSING, and it stays ACTIVE even if processing_status becomes
    # FAILED - AI enrichment failing must never un-publish a job.
    # ------------------------------------------------------------------
    status = Column(String(20), nullable=False, server_default="ACTIVE")

    processing_status = Column(String(20), nullable=False, server_default="PENDING")
    processing_error = Column(Text, nullable=True)

    # SHA-256 of the description text the embedding/requirements were
    # generated from. Used to skip reprocessing on edits that don't touch
    # the description (e.g. salary/location-only updates).
    description_hash = Column(String(64), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    company = relationship(
        "Company",
        back_populates="jobs"
    )

    applications = relationship(
        "Application",
        back_populates="job",
        cascade="all, delete"
    )