"""Exercise the bounded pre-banner lookup with real parsing and token accounting."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configuration import LLMSettings, Settings
from src.nodes.fill import _decision_line
from src.state import Task4Outcome, Task5Outcome
from src.tools.derived_answers import load_derived_answers
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_validation.required_answers import AnswerAttempts, recover_required
from src.tools.llm_answers import QuestionDecision
from src.tools.token_usage import runtime


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, llm=LLMSettings(api_key="test", model="test"))
    answers = {"years using python": "5"}
    first = AsyncMock(return_value=QuestionDecision())
    ask = AsyncMock(return_value=None)
    client = MagicMock()
    client.__aenter__.return_value = client
    create = AsyncMock()
    client.chat.completions.create = create
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: client)
    attempts = AnswerAttempts(settings, Task5Outcome(), first, ask, None, answers)
    return attempts, create


def reply(create, answer, keys):
    message = SimpleNamespace(content=json.dumps({"answer": answer, "source_keys": keys}))
    create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage={"prompt_tokens": 7},
    )


@pytest.mark.parametrize("answer,kind,options", [
    ("5", "text", []), ("Yes", "radio", ["Yes", "No"]),
])
async def test_grounded_reread(setup, answer, kind, options):
    attempts, create = setup
    reply(create, answer, ["years using python"])
    before = runtime.tracker.snapshot()
    decision = await attempts.choose("Python experience?*", kind, options)
    assert decision.answer == answer and decision.second_look
    assert decision.source_keys == ["years using python"]
    assert runtime.tracker.snapshot().input == before.input + 7
    assert runtime.tracker.snapshot().calls == before.calls + 1
    cache = load_derived_answers(attempts.settings.derived_answers_file)
    if answer == "Yes":
        assert cache["python experience"].source_snapshot == attempts.answers
    else:
        assert cache == {}
    assert not attempts.settings.answers_file.exists()
    attempts.asker.assert_not_awaited()
    create.assert_awaited_once()


@pytest.mark.parametrize("failure", ["unsourced", "invented", "option", "exception", "empty"])
async def test_miss_reaches_one_banner(setup, failure):
    attempts, create = setup
    attempts.chooser.return_value = QuestionDecision(answer="Unavailable")
    attempts.answers["choice"] = "Unavailable"
    answer = {"option": "5", "empty": "", "invented": "Impossible"}.get(failure, "Yes")
    reply(create, answer, [] if failure == "unsourced" else ["years using python"])
    if failure == "exception":
        create.side_effect = TimeoutError()
    for _ in range(2):
        assert not (await attempts.choose("Choice*", "select", ["Yes", "No"])).decided
        await attempts.ask("Choice*", {"type": "select"})
    attempts.chooser.assert_awaited_once()
    create.assert_awaited_once()
    attempts.asker.assert_awaited_once()
    assert "first pass and second look" in attempts.human.notes.lower()


@pytest.mark.parametrize("case", ["first", "empty", "no_model", "job_specific", "disabled"])
async def test_skip_conditions(setup, case):
    attempts, create = setup
    if case == "first":
        attempts.chooser.return_value = QuestionDecision(answer="5")
    elif case == "empty":
        attempts.answers.clear()
    elif case == "no_model":
        attempts.settings.llm.model = None
    elif case == "disabled":
        attempts.settings.session.ask_human = False
    else:
        attempts.chooser.return_value = QuestionDecision(job_specific=True, rationale="no evidence")
    decision = await attempts.choose("Years using Python*", "text", [])
    assert decision.decided == (case == "first")
    assert not attempts.audit()[0].second_attempted
    if case == "job_specific":
        await attempts.ask("Years using Python*", {"type": "text"})
        attempts.asker.assert_awaited_once()
    create.assert_not_awaited()


@pytest.mark.parametrize("bad", ["Select an option", " Tools? ", " "])
async def test_unusable_exact_cannot_override_grounded_reread(setup, bad):
    attempts, create = setup
    attempts.answers["tools"] = bad
    reply(create, "5", ["years using python"])
    assert (await attempts.choose("Tools*", "text", [])).answer == "5"


async def test_select_value_still_fits_when_label_differs(setup):
    from src.tools.answer_second_look import SelectLabels

    attempts, create = setup
    options = SelectLabels([{"text": "Australia", "value": "AU"}])
    attempts.chooser.return_value = QuestionDecision(answer="AU")
    assert (await attempts.choose("Country*", "select", options)).answer == "AU"
    assert list(options) == ["Australia"]
    assert not attempts.audit()[0].second_attempted
    create.assert_not_awaited()


async def test_configured_deadline_records_one_call_and_falls_back(setup):
    attempts, create = setup
    attempts.settings.llm.timeout_seconds = 0.05

    async def stalled(**kwargs):
        await asyncio.Event().wait()

    create.side_effect = stalled
    before = runtime.tracker.snapshot()
    decision = await asyncio.wait_for(attempts.choose("Language*", "text", []), 2)
    assert not decision.decided and "TimeoutError" in decision.rationale
    assert runtime.tracker.snapshot().unavailable == before.unavailable + 1
    await attempts.ask("Language*", {"type": "text"})
    attempts.asker.assert_awaited_once()


async def test_recovery_uses_live_exact_store(setup):
    attempts, create = setup
    field = dict(kind="input", type="text", question="  YEARS using Python?*", marker="f", value="")
    page = MagicMock()
    async def evaluate(script, *values):
        if values:
            field["value"] = values[0]
    element = AsyncMock()
    element.evaluate.side_effect = evaluate
    page.get_elements_by_css_selector = AsyncMock(return_value=[element])
    outcome = Task4Outcome()
    ok, reason = await recover_required(
        page, [dict(field=field)], outcome, attempts,
        AsyncMock(return_value=(True, "", [field], "")),
    )
    assert ok, reason
    assert field["value"] == "5" and outcome.fields[0].second_look
    assert "second look" in _decision_line(outcome.fields[0])
    create.assert_not_awaited()
    attempts.asker.assert_not_awaited()


async def test_fill_step_ticks_exact_multiselect(setup):
    attempts, create = setup
    attempts.answers["tools"] = "Python, Rust"
    fields = [
        dict(kind="checkbox", type="checkbox", question="Tools*", option=option,
             marker=option, name="tools", required=True) for option in ("Python", "Rust", "Go")
    ]
    elements = {f["marker"]: AsyncMock() for f in fields}
    page = AsyncMock()
    page.evaluate.return_value = '{"selected":[]}'
    page.get_elements_by_css_selector.side_effect = lambda selector: [
        el for key, el in elements.items() if f'"{key}"' in selector
    ]
    known, filled, unknown, records = await _fill_step(
        page, fields, attempts.answers, attempts.settings,
        ask=attempts.ask, chooser=attempts.choose,
    )
    assert (known, filled, unknown) == (1, 1, [])
    assert records[0].second_look and records[0].answered_by == "llm"
    for key in ["Python", "Rust"]:
        elements[key].check.assert_awaited_once()
    elements["Go"].check.assert_not_awaited()
    create.assert_not_awaited()
    attempts.asker.assert_not_awaited()
    assert not attempts.settings.answers_file.exists()


async def test_single_negative_checkbox_leaves_box_clear_without_banner(setup):
    from src.tools.linkedin_validation.required_controls import usable_answer

    attempts, create = setup
    attempts.answers["subscribe"] = "No"
    field = dict(kind="checkbox", type="checkbox", question="Subscribe*", option="Subscribe",
                 marker="s", name="subscribe", required=True)
    assert usable_answer([field], "No")
    page = AsyncMock()
    _, filled, unknown, records = await _fill_step(
        page, [field], attempts.answers, attempts.settings, ask=attempts.ask,
        chooser=attempts.choose,
    )
    assert filled == 1 and not unknown
    assert records[0].second_look and records[0].value == "No"
    create.assert_not_awaited()
    attempts.asker.assert_not_awaited()
