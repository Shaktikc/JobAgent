"""Stable public state API; models are split by concern (415-line limit)."""

from src.state.core import AgentOutcome, ApplyState, new_state
from src.state.forms import Task4Outcome, Task5Outcome
from src.state.outcomes import (
    DEFAULT_LOGIN_URL,
    DEFAULT_SEARCH_QUERY,
    FormField,
    JobAnswerContext,
    JobContextAudit,
    JobDescription,
    ResumeCandidate,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
)
from src.state_loop import SkippedJobRecord, Task8JobRecord, Task8Outcome, Task16Outcome

__all__ = [
    "AgentOutcome",
    "ApplyState",
    "new_state",
    "Task4Outcome",
    "Task5Outcome",
    "DEFAULT_LOGIN_URL",
    "DEFAULT_SEARCH_QUERY",
    "FormField",
    "JobAnswerContext",
    "JobContextAudit",
    "JobDescription",
    "ResumeCandidate",
    "Task1Outcome",
    "Task2Outcome",
    "Task3Outcome",
    "SkippedJobRecord",
    "Task8JobRecord",
    "Task8Outcome",
    "Task16Outcome",
]
