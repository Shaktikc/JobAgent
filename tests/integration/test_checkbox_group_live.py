"""Opt-in live-browser test for an SDUI checkbox ("select all that apply") group.

BUG-059: LinkedIn's current Easy Apply markup renders the question in a ``<p>``
above a bare ``<fieldset>`` (no legend, no aria-label), each option as a
``div[role=checkbox]`` whose inner ``label[for]`` is empty and whose text sits in a
sibling ``<p>``, and ticking re-renders the wrapper (dropping our marker). The group
used to be enumerated as one question per option and the human's ticks were never
saved. The markup below is copied from the live Propeller Aero application.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_FILL_LIVE="1"
    uv run pytest tests/integration/test_checkbox_group_live.py -s

Skipped by default so the unit suite stays fast and offline.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_FILL_LIVE"),
        reason="set AUTOJOB_FILL_LIVE=1 to run the live checkbox-group test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

QUESTION = "Before you applied, where did you first encounter Propeller Aero?*"
OPTIONS = [
    "LinkedIn Job Ad",
    "LinkedIn Social Post",
    "Glassdoor",
    "YouTube",
    "Friend/Referral",
    "Google Search",
]
_TICKED = ["LinkedIn Job Ad", "LinkedIn Social Post", "Google Search"]

_OPTIONS_HTML = "".join(
    '<div role="checkbox" tabindex="0" aria-checked="false"><div><div>'
    '<input type="checkbox" tabindex="-1"><label></label></div>'
    f"<p>{option}</p></div></div>"
    for option in OPTIONS
)

_SCRIPT = """<script>
  document.addEventListener('click', function (e) {
    const box = e.target.closest && e.target.closest('[role="checkbox"]');
    if (!box) return;
    // React-like re-render: the fresh node carries the new state while the old
    // node (which the answer watcher still holds) keeps aria-checked="false" and
    // loses data-autojob-fill. This is what made the human's tick unreadable.
    const clone = box.cloneNode(true);
    const on = box.getAttribute('aria-checked') === 'true';
    clone.setAttribute('aria-checked', on ? 'false' : 'true');
    clone.removeAttribute('data-autojob-fill');
    box.replaceWith(clone);
  });
  window.__tick = function (text) {
    const box = Array.from(document.querySelectorAll('[role="checkbox"]'))
      .find((b) => (b.innerText || '').trim() === text);
    if (!box) return false;
    (box.querySelector('p') || box).click();
    return true;
  };
</script>"""

# The question sits inside the field's wrapper; the group is a bare <fieldset>.
_FORM_HTML = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SDUI checkbox group</title></head>
<body>
<dialog open>
  <h2>Apply to Propeller</h2>
  <div>
    <p>{QUESTION}</p>
    <fieldset aria-describedby="error-message-x"><div>{_OPTIONS_HTML}</div></fieldset>
  </div>
  <footer><button type="button" id="submit-btn">Submit application</button></footer>
</dialog>
{_SCRIPT}
</body></html>
"""

# The same group rendered directly in the modal's scroller (no field wrapper): the
# question is still the fieldset's preceding <p>.
_FORM_HTML_DIRECT = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SDUI checkbox group</title></head>
<body>
<dialog open>
  <h2>Apply to Propeller</h2>
  <p>{QUESTION}</p>
  <fieldset aria-describedby="error-message-x"><div>{_OPTIONS_HTML}</div></fieldset>
  <footer><button type="button" id="submit-btn">Submit application</button></footer>
</dialog>
{_SCRIPT}
</body></html>
"""

_READ_STATE_JS = """() => JSON.stringify({
  ticks: Array.from(document.querySelectorAll('[role="checkbox"]'))
    .filter((el) => el.getAttribute('aria-checked') === 'true')
    .map((el) => (el.innerText || '').replace(/\\s+/g, ' ').trim()),
  banner: !!document.getElementById('autojob-unknown')
})"""


def _settings(tmp_path: Path, *, ask_timeout: float = 60.0) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            ask_human=True,
            ask_timeout_seconds=ask_timeout,
            ask_poll_seconds=0.2,
            post_click_wait_seconds=0.0,
        ),
        data_dir=tmp_path / "data",
    )


async def _open_fixture(tmp_path: Path, browser, html: str):
    """Serve ``html`` from a local file and open it in a fresh page."""
    form_file = tmp_path / "sdui_checkbox.html"
    form_file.write_text(html, encoding="utf-8")
    page = await browser.new_page()
    await page.goto(form_file.as_uri())
    await browser_tools._wait_for_load(page, 10)
    return page


async def _unknown(question: str, field_type: str, options: list[str]) -> QuestionDecision:
    return QuestionDecision(question=question)


async def test_sdui_checkbox_group_is_one_question_and_keeps_the_human_ticks(
    tmp_path: Path,
) -> None:
    """All options share the question; three ticks are asked once and all saved."""
    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await _open_fixture(tmp_path, browser, _FORM_HTML)

        # Every option is enumerated under the group's question (not its own text),
        # and the hint lists the whole option list.
        opened, _title, fields, _step = await browser_tools.read_form(page)
        assert opened is True
        assert [f["option"] for f in fields] == OPTIONS
        assert {f["question"] for f in fields} == {QUESTION}

        human = Task5Outcome()
        fill_task = asyncio.create_task(
            browser_tools._task4_on_page(
                page, browser, None, {}, settings, lambda _m: None,
                human=human, chooser=_unknown,
            )
        )

        appeared = False
        for _ in range(200):
            payload = json.loads(await page.evaluate(browser_tools._READ_UNKNOWN_JS))
            if payload.get("present"):
                appeared = True
                break
            await asyncio.sleep(0.05)
        assert appeared, "the Task 5 banner never appeared"

        banner = await page.evaluate(
            "() => document.getElementById('autojob-unknown').innerText"
        )
        assert QUESTION in banner
        assert "One of: " + ", ".join(OPTIONS) in banner

        for option in _TICKED:
            clicked = await page.evaluate(f"() => window.__tick({option!r})")
            assert str(clicked).lower() == "true", option
            await asyncio.sleep(0.4)

        assert not fill_task.done()
        assert browser_tools.load_answers(settings.answers_file) == {}
        await page.evaluate("() => document.getElementById('autojob-unknown-done').click()")
        outcome = await asyncio.wait_for(fill_task, timeout=60)
        state = json.loads(await page.evaluate(_READ_STATE_JS))
        stored = browser_tools.load_answers(settings.answers_file)

        # The ticks stay on the page and every one of them was stored once, under
        # the group's real question.
        assert sorted(state["ticks"]) == sorted(_TICKED)
        assert state["banner"] is False
        assert stored.get(
            "before you applied, where did you first encounter propeller aero"
        ) == ", ".join(_TICKED)
        assert human.asked == 1 and human.answered == 1
        record = outcome.fields[0]
        assert record.question == QUESTION
        assert record.field_type == "checkbox"
        assert record.value == ", ".join(_TICKED)
        assert record.filled is True and record.error == ""
    finally:
        await browser.kill()
        # Collect browser-use's pipe transport here, while this test's warning
        # filter is active (it otherwise fires after the session has ended).
        gc.collect()


async def test_stored_multi_select_answer_ticks_the_group_without_a_prompt(
    tmp_path: Path,
) -> None:
    """A remembered "A, B" answer ticks both boxes and never shows the banner."""
    settings = _settings(tmp_path, ask_timeout=10.0)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await _open_fixture(tmp_path, browser, _FORM_HTML_DIRECT)
        answer = "LinkedIn Job Ad, Google Search"

        async def chooser(
            question: str, field_type: str, options: list[str]
        ) -> QuestionDecision:
            return QuestionDecision(
                question=question, category="test", answer=answer, matched_key="stored"
            )

        human = Task5Outcome()
        outcome = await browser_tools._task4_on_page(
            page, browser, None, {}, settings, lambda _m: None,
            human=human, chooser=chooser,
        )
        state = json.loads(await page.evaluate(_READ_STATE_JS))

        assert sorted(state["ticks"]) == sorted(answer.split(", "))
        assert state["banner"] is False
        assert human.asked == 0
        record = outcome.fields[0]
        assert record.value == answer
        assert record.filled is True and record.error == ""
    finally:
        await browser.kill()
        gc.collect()
