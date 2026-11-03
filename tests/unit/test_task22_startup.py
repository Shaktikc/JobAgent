"""Startup submission consent and its persistence into graph state."""

import io

import pytest

from src.state import new_state
from src.submission_choice import choose_submission_mode


@pytest.mark.parametrize("answer,expected", [
    ("", "manual"), ("1", "manual"), ("manual", "manual"),
    ("2", "auto"), (" auto ", "auto"), ("Automatic", "auto"),
])
def test_interactive_choice(answer, expected):
    output = io.StringIO()
    assert choose_submission_mode(
        interactive=True, input_func=lambda _: answer, stream=output,
    ) == expected
    assert "for this run" in output.getvalue()


def test_noninteractive_default_does_not_ask():
    output = io.StringIO()
    assert choose_submission_mode(interactive=False, stream=output) == "manual"
    assert not output.getvalue()


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_interrupted_choice_is_manual(error):
    def interrupted(_):
        raise error
    assert choose_submission_mode(interactive=True, input_func=interrupted) == "manual"


def test_invalid_answers_are_bounded_and_can_be_corrected():
    answers = iter(["bad", "2"])
    assert choose_submission_mode(interactive=True, input_func=lambda _: next(answers)) == "auto"
    assert choose_submission_mode(interactive=True, input_func=lambda _: "bad") == "manual"
    with pytest.raises(ValueError):
        choose_submission_mode("invalid")


@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_explicit_mode_skips_prompt(mode):
    def unexpected(_):
        pytest.fail("explicit mode must not prompt")
    assert choose_submission_mode(mode, interactive=True, input_func=unexpected) == mode


def test_choice_is_resolved_before_run_and_reaches_state(monkeypatch):
    import src.main as cli
    from src.configuration import Settings

    events = []
    async def invoke(state, config):
        events.append("run")
        assert state["submission_mode"] == "auto"
        return {**state, "status": "done"}
    monkeypatch.setattr(cli, "choose_date_range", lambda _: "past_week")
    monkeypatch.setattr(cli, "choose_submission_mode", lambda _: events.append("choice") or "auto")
    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli.graph, "ainvoke", invoke)
    assert cli.main(["--no-dry-run"]) == 0
    assert events == ["choice", "run"]
    assert new_state()["submission_mode"] == "manual"


@pytest.mark.parametrize("flag", ["--clean-profile", "--describe-new-resumes"])
def test_maintenance_modes_never_ask(monkeypatch, flag):
    import src.main as cli

    def unexpected(_):
        pytest.fail("maintenance mode must not prompt")
    async def describe(_):
        return 0
    monkeypatch.setattr(cli, "choose_submission_mode", unexpected)
    monkeypatch.setattr(cli, "_clean_profile", lambda: 0)
    monkeypatch.setattr(cli, "_describe_new_resumes", describe)
    assert cli.main([flag]) == 0


def test_confirmation_timeout_can_be_configured(monkeypatch):
    from src.configuration import load_settings

    monkeypatch.setenv("AUTOJOB_SESSION_AUTO_SUBMIT_TIMEOUT_SECONDS", "12.5")
    assert load_settings().session.auto_submit_timeout_seconds == 12.5
