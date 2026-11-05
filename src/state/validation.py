"""Metadata-only outcomes for Task 20; rejected answer values are never stored."""

from pydantic import BaseModel, Field

from src.state.type_conversion import TypeConversionAttempt


class ValidationIssue(BaseModel):
    question: str = ""
    message: str = ""


class RequiredAnswerAttempt(BaseModel):
    question: str = ""
    automatic_attempted: bool = False
    human_prompted: bool = False
    failure: str = ""


class ValidationFailure(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    correction_attempted: bool = False
    retry_count: int = 0
    correction_failure: str = ""
    required_answer_attempts: list[RequiredAnswerAttempt] = Field(default_factory=list)
    type_conversion_attempts: list[TypeConversionAttempt] = Field(default_factory=list)
    job_url: str = ""
    job_id: str = ""
    log_path: str = ""
    logged: bool = False
    modal_closed: bool = False
    error: str = ""

    @property
    def skipped(self) -> bool:
        return bool(self.issues and self.logged and self.modal_closed)


class Task20Outcome(BaseModel):
    jobs_skipped: int = 0
    skipped: list[ValidationFailure] = Field(default_factory=list)
