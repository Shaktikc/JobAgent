"""Recovery resolves grounded answers, excludes optional fields and contains errors."""

from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome, Task5Outcome
from src.tools.linkedin_validation import navigation, required_answers, required_controls
from src.tools.llm_answers import QuestionDecision


def field(kind="input", question="Experience*", **kwargs):
    return dict(
        kind=kind,
        type="text" if kind == "input" else kind,
        question=question,
        name="one",
        marker="f0",
        value="",
        checked=False,
        **kwargs,
    )


@pytest.mark.parametrize("human_answer", ["Two years", None])
async def test_human_answer_or_skip_is_bounded(tmp_path, monkeypatch, human_answer):
    original = field()
    current = dict(original)
    calls = []
    outcome = Task4Outcome()

    async def read(_page):
        return True, "Step", [current], "step"

    async def choose(question, *args):
        calls.append("automatic")
        return QuestionDecision(question=question)

    async def ask(question, prompt):
        calls.append("human")
        assert prompt["markers"] == ["fresh"]
        current["value"] = human_answer or ""
        return human_answer

    async def apply(*args):
        return current["value"] == human_answer

    async def rerender(question, *args):
        result = await choose(question, *args)
        current["marker"] = "fresh"
        return result

    monkeypatch.setattr(required_answers, "apply_answer", apply)
    attempts = required_answers.AnswerAttempts(
        Settings(data_dir=tmp_path),
        Task5Outcome(),
        rerender,
        ask,
        lambda _: None,
    )
    issue = dict(question=original["question"], field=original, message="This field is required")
    ok, reason = await required_answers.recover_required(
        None, [issue, issue], outcome, attempts, read
    )
    assert ok is bool(human_answer)
    assert calls == ["automatic", "human"]
    if human_answer:
        assert outcome.filled_fields == 1 and not reason
    else:
        assert "skipped" in reason
        await required_answers.recover_required(None, [issue], outcome, attempts, read)
        assert calls == ["automatic", "human"]


@pytest.mark.parametrize("kind", ["input", "textarea", "select", "radio", "checkbox"])
async def test_unstarred_question_never_resolves(tmp_path, kind):
    optional = field(kind, "Optional", required=True)

    async def forbidden(*args):
        pytest.fail("an optional question must never be read, answered or prompted")

    attempts = required_answers.AnswerAttempts(
        Settings(data_dir=tmp_path),
        Task5Outcome(),
        forbidden,
        forbidden,
        lambda _: None,
    )
    ok, reason = await required_answers.recover_required(
        None,
        [dict(field=optional)],
        Task4Outcome(),
        attempts,
        forbidden,
    )
    assert not ok and "marker" in reason


@pytest.mark.parametrize("where", ["detect", "read", "chooser", "banner", "click", "buttons"])
async def test_recovery_exceptions_never_escape(tmp_path, monkeypatch, where):
    control = field()
    current = (True, "Step", [control], "step")
    issue = dict(question=control["question"], field=control, message="This field is required")

    async def fail(*args):
        raise RuntimeError("untrusted external details")

    async def detect(*args):
        return [issue]

    async def read(*args):
        return current

    async def choose(question, *args):
        return QuestionDecision(
            question=question, answer=None if where == "banner" else "Two years"
        )

    async def apply(*args):
        return True

    async def buttons(*args):
        return [{"marker": "b0", "text": "Review", "disabled": False}]

    async def marker(*args):
        return SimpleNamespace(click=fail, evaluate=read)

    monkeypatch.setattr(navigation, "read_rejections", fail if where == "detect" else detect)
    monkeypatch.setattr(navigation, "_marker_element", marker)
    monkeypatch.setattr(required_answers, "apply_answer", apply)
    settings = Settings(data_dir=tmp_path, session=SessionSettings(easy_apply_timeout_seconds=0.01))
    attempts = required_answers.AnswerAttempts(
        settings,
        Task5Outcome(),
        fail if where == "chooser" else choose,
        fail,
        lambda _: None,
    )
    outcome = Task4Outcome()
    await navigation.finish_advance(
        None,
        current,
        "step",
        settings,
        lambda _: None,
        outcome,
        choose,
        {},
        read=fail if where == "read" else read,
        buttons=fail if where == "buttons" else buttons,
        signature_of=lambda *args: "step",
        blur=read,
        required_attempts=attempts,
    )
    assert outcome.validation.issues
    assert "RuntimeError" in outcome.validation.correction_failure
    assert not outcome.submitted


def test_filled_format_error_is_left_to_value_correction():
    control = field(value_ignored="")
    control["value"] = "two years"
    assert not required_controls.is_missing_issue(
        dict(field=control, message="Please enter a valid number"),
        [control],
    )


async def test_recovery_has_a_five_question_cap_and_preserves_committed_answers(
    tmp_path, monkeypatch
):
    fields = [field(question=f"Question {index}*") for index in range(6)]
    for control in fields:
        control["value"] = "Committed answer"
    applied = []

    async def read(*args):
        return True, "Step", fields, "step"

    async def apply(page, control, answer, reader):
        applied.append(answer)
        return True

    async def forbidden(*args):
        pytest.fail("committed answers must precede chooser and human calls")

    monkeypatch.setattr(required_answers, "apply_answer", apply)
    attempts = required_answers.AnswerAttempts(
        Settings(data_dir=tmp_path),
        Task5Outcome(),
        forbidden,
        forbidden,
        lambda _: None,
    )
    ok, reason = await required_answers.recover_required(
        None,
        [dict(field=control) for control in fields],
        Task4Outcome(),
        attempts,
        read,
    )
    assert not ok and "five" in reason
    assert applied == ["Committed answer"] * 5


async def test_pending_value_correction_still_resolves_missing_questions(tmp_path, monkeypatch):
    control = field()
    current = (True, "Step", [control], "step")
    calls = []

    async def detect(*args):
        return [dict(field=control, question=control["question"], message="This field is required")]

    async def recover(*args):
        calls.append("resolved")
        return True, ""

    async def read(*args):
        return (True, "Review", [], "review") if calls else current

    async def buttons(*args):
        return [{"marker": "b0", "text": "Review", "disabled": False}]

    async def marker(*args):
        return SimpleNamespace(click=read, evaluate=read)

    monkeypatch.setattr(navigation, "read_rejections", detect)
    monkeypatch.setattr(navigation, "recover_required", recover)
    monkeypatch.setattr(navigation, "_marker_element", marker)
    outcome = Task4Outcome()
    await navigation.finish_advance(
        None,
        current,
        "step",
        Settings(data_dir=tmp_path),
        lambda _: None,
        outcome,
        None,
        {"step": False},
        read=read,
        buttons=buttons,
        signature_of=lambda t, f, step: step,
        blur=read,
    )
    assert calls == ["resolved"] and not outcome.validation.issues


async def test_skipped_partial_answer_is_never_adopted_or_used_to_navigate(tmp_path, monkeypatch):
    control = field()

    async def skipped(question, prompt):
        control["value"] = "Unfinished prefix"
        return None

    async def read(*args):
        return True, "Step", [control], "step"

    async def detect(*args):
        return []

    async def forbidden(*args):
        pytest.fail("an unfinished human answer must never cause navigation")

    settings = Settings(data_dir=tmp_path, session=SessionSettings(easy_apply_timeout_seconds=0.01))
    attempts = required_answers.AnswerAttempts(
        settings,
        Task5Outcome(),
        None,
        skipped,
        lambda _: None,
    )
    attempts.step = "step"
    assert await attempts.ask(control["question"], control) is None
    monkeypatch.setattr(navigation, "read_rejections", detect)
    outcome = Task4Outcome()
    await navigation.finish_advance(
        None,
        await read(),
        "step",
        settings,
        lambda _: None,
        outcome,
        None,
        {},
        read=read,
        buttons=forbidden,
        signature_of=lambda t, f, step: step,
        blur=forbidden,
        required_attempts=attempts,
    )
    assert outcome.validation.issues
    assert not outcome.filled_fields
    assert "skipped" in outcome.validation.correction_failure
