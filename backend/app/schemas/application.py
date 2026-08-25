from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    candidate_id: int
    job_id: int


class ApplicationUpdate(BaseModel):
    status: str


class ApplicationResponse(BaseModel):
    id: int

    candidate_id: int

    job_id: int

    status: str

    # AI analysis is now produced asynchronously in the background, so it
    # is not guaranteed to exist yet when the application row is returned
    # from the submission endpoint. All AI-derived fields are optional.
    analysis_status: str = "PENDING"

    match_score: int | None = None

    matched_skills: str | None = None

    missing_skills: str | None = None

    ai_recommendation: str | None = None

    ai_summary: str | None = None

    interview_questions: list[str] | None = None

    class Config:
        from_attributes = True


class ApplicationStatusResponse(BaseModel):
    """Lightweight payload for polling AI-analysis progress."""

    application_id: int
    application_status: str
    analysis_status: str
    match_score: int | None = None

    class Config:
        from_attributes = True