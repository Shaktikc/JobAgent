"""Validation remains bounded even after swallowed clicks or correction errors."""

from types import SimpleNamespace

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools.linkedin_validation import correction, navigation

ISSUES = [{"question": "Salary*", "message": "Invalid input", "field": {}}]
CURRENT = (True, "step one", [], "one")


async def run_navigation(monkeypatch, reject_after_retry=False, correction_error=False):
    state = {"clicks": 0, "corrections": 0}
    outcome = Task4Outcome()

    async def detect(*args):
        return ISSUES if not reject_after_retry or state["clicks"] else []

    async def correct(*args):
        state["corrections"] += 1
        if correction_error:
            raise RuntimeError("correction failed")
        return True, True

    async def click():
        state["clicks"] += 1

    async def marker(*args):
        async def evaluate(*args):
            pass
        return SimpleNamespace(click=click, evaluate=evaluate)

    async def read(*args):
        return (
            (True, "step two", [], "two")
            if state["corrections"] and not correction_error
            else CURRENT
        )

    async def buttons(*args):
        return [{"marker": "next", "text": "Next", "disabled": False}]

    async def blur(*args):
        pass

    monkeypatch.setattr(navigation, "read_rejections", detect)
    monkeypatch.setattr(navigation, "correct_rejections", correct)
    monkeypatch.setattr(navigation, "_marker_element", marker)
    result = await navigation.finish_advance(
        None,
        CURRENT,
        "one",
        Settings(session=SessionSettings(easy_apply_timeout_seconds=0.001)),
        lambda _: None,
        outcome,
        None,
        {},
        read=read,
        buttons=buttons,
        signature_of=lambda title, fields, step: step,
        blur=blur,
    )
    return result, state, outcome


async def test_validation_appearing_only_after_generic_retry_is_corrected(monkeypatch):
    result, state, outcome = await run_navigation(monkeypatch, reject_after_retry=True)
    assert result[-1] == "two"
    assert state == {"clicks": 2, "corrections": 1}
    assert not outcome.validation.issues


async def test_correction_exception_preserves_rejection_for_safe_logging(monkeypatch):
    _, state, outcome = await run_navigation(monkeypatch, correction_error=True)
    assert outcome.validation.issues
    assert "correction" in outcome.validation.correction_failure
    assert state["clicks"] == 0


async def test_unrelated_unknown_question_keeps_human_flow_after_repair(monkeypatch):
    async def detect(*args):
        return ISSUES

    async def correct(*args):
        return True, True

    monkeypatch.setattr(correction, "read_rejections", detect)
    monkeypatch.setattr(correction, "correct_rejections", correct)
    corrected_steps = {}
    await correction.reject_before_human_prompt(
        None,
        [],
        "Different question*",
        None,
        Task4Outcome(),
        lambda _: None,
        corrected_steps,
        "step",
    )
    assert corrected_steps == {"step": False}  # Navigation retry remains available.
