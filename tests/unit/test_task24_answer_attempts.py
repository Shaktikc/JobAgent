"""Required-answer work is bounded per question and form step."""

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision


async def test_automatic_and_human_attempts_are_not_repeated(tmp_path):
    calls = []

    async def choose(question, kind, options):
        calls.append("automatic")
        return QuestionDecision(question=question)

    async def ask(question, field):
        calls.append("human")
        return None

    attempts = AnswerAttempts(
        Settings(data_dir=tmp_path), Task5Outcome(), choose, ask, calls.append
    )
    attempts.step = "first"
    for _ in range(2):
        await attempts.choose("Tools*", "radio", ["Yes", "No"])
        await attempts.ask("Tools*", {"type": "radio"})
    assert calls.count("automatic") == calls.count("human") == 1
    attempts.step = "second"
    await attempts.ask("Tools*", {"type": "radio"})
    assert calls.count("human") == 2
    assert attempts.audit()[0].human_prompted


async def test_human_disabled_never_waits(tmp_path):
    async def forbidden(*args):
        raise AssertionError("human disabled")

    attempts = AnswerAttempts(
        Settings(data_dir=tmp_path, session=SessionSettings(ask_human=False)),
        Task5Outcome(),
        None,
        forbidden,
        lambda _: None,
    )
    assert await attempts.ask("Tools*", {"type": "radio"}) is None
    assert not attempts.audit()[0].human_prompted
