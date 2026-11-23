"""Task 12 preserves the automatic decision before the human handoff."""
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision


async def test_role_interest_rejection_survives_human_skip():
    from src.configuration import Settings

    question = "Why are you interested in this role?*"
    reason = "the cited resume evidence was not found in that source"
    calls = []

    async def choose(question, kind, options):
        calls.append("automatic")
        return QuestionDecision(question=question, job_specific=True, rationale=reason)

    async def ask(question, field):
        calls.append("human")

    settings = Settings()
    settings.session.ask_human = True
    attempts = AnswerAttempts(settings, None, choose, ask, None)
    await attempts.choose(question, "textarea", [])
    await attempts.ask(question, {"type": "textarea"})
    entry, = attempts.audit()
    assert calls == ["automatic", "human"]
    assert entry.job_context_rejection == reason
    assert entry.failure
