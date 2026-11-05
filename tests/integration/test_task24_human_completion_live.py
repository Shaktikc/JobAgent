"""Shared Task 5 completion gates used by required-question recovery."""

import asyncio
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.browser import build_browser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.form_queries import read_form

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"),
    reason="set AUTOJOB_FILL_LIVE=1",
)


@pytest.mark.parametrize("finish", ["done", "blur", "enter", "skip", "timeout"])
async def test_unfinished_text_never_reaches_the_store(tmp_path, finish, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=True,
            ask_poll_seconds=0.02,
            ask_timeout_seconds=0.4,
        ),
    )
    monkeypatch.setattr("src.tools.linkedin_ask_human.flow._SAVED_VISIBLE_SECONDS", 0)
    browser = build_browser(settings)
    await browser.start()
    waiter = None
    try:
        fixture = tmp_path / "human.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2>
          <label for="answer">Experience*</label><input id="answer">
          <button>Review</button></dialog>""",
            encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        _, _, fields, _ = await read_form(page)
        waiter = asyncio.create_task(
            ask_human_for_answer(
                page,
                "Experience*",
                "text",
                "",
                settings,
                lambda _: None,
                Task5Outcome(),
                markers=[fields[0]["marker"]],
            )
        )
        for _ in range(50):
            if (
                str(await page.evaluate("() => !!document.getElementById('autojob-unknown')"))
                == "True"
            ):
                break
            await asyncio.sleep(0.02)
        await page.evaluate("""() => {
            const el=document.getElementById('answer'); el.focus(); el.value='Two';
            el.dispatchEvent(new Event('input',{bubbles:true}));
        }""")
        await asyncio.sleep(0.08)
        assert load_answers(settings.answers_file) == {}
        assert not waiter.done()
        # Keep editing for longer than the original inactivity deadline.
        for value in ("Two y", "Two ye", "Two yea", "Two year"):
            await page.evaluate("""(value) => {
                const el=document.getElementById('answer'); el.value=value;
                el.dispatchEvent(new Event('input',{bubbles:true}));
            }""", value)
            await asyncio.sleep(0.15)
            assert not waiter.done()
            assert load_answers(settings.answers_file) == {}
        await page.evaluate("""() => {
            const el=document.getElementById('answer'); el.value='Two years';
            el.dispatchEvent(new Event('input',{bubbles:true}));
        }""")
        if finish == "done":
            await page.evaluate("() => document.getElementById('autojob-unknown-done').click()")
        elif finish == "blur":
            await page.evaluate("() => document.getElementById('answer').blur()")
        elif finish == "enter":
            await page.evaluate("""() => document.getElementById('answer').dispatchEvent(
                new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))""")
        elif finish == "skip":
            await page.evaluate("() => document.getElementById('autojob-unknown-skip').click()")
        result = await asyncio.wait_for(waiter, 3)
        assert result == (None if finish in ("timeout", "skip") else "Two years")
        assert load_answers(settings.answers_file) == (
            {} if finish in ("timeout", "skip") else {"experience": "Two years"}
        )
    finally:
        if waiter and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await browser.kill()


async def test_checkbox_group_waits_for_done_and_saves_the_whole_selection(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=True,
            ask_poll_seconds=0.02,
            ask_timeout_seconds=3,
        ),
    )
    monkeypatch.setattr("src.tools.linkedin_ask_human.flow._SAVED_VISIBLE_SECONDS", 0)
    browser = build_browser(settings)
    await browser.start()
    waiter = None
    try:
        fixture = tmp_path / "checkboxes.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2><fieldset>
          <legend>Tools*</legend><label><input id="a" type="checkbox" name="tools">Red</label>
          <label><input id="b" type="checkbox" name="tools">Blue</label>
          </fieldset><button>Review</button></dialog>""",
            encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        fields = (await read_form(page))[2]
        waiter = asyncio.create_task(
            ask_human_for_answer(
                page,
                "Tools*",
                "checkbox",
                "Red, Blue",
                settings,
                lambda _: None,
                Task5Outcome(),
                markers=[f["marker"] for f in fields],
                name="tools",
                options=["Red", "Blue"],
            )
        )
        for _ in range(50):
            if (
                str(await page.evaluate("() => !!document.getElementById('autojob-unknown')"))
                == "True"
            ):
                break
            await asyncio.sleep(0.02)
        await page.evaluate("() => document.getElementById('a').click()")
        await asyncio.sleep(0.15)
        assert not waiter.done() and load_answers(settings.answers_file) == {}
        await page.evaluate("() => document.getElementById('b').click()")
        await asyncio.sleep(0.05)
        await page.evaluate("() => document.getElementById('autojob-unknown-done').click()")
        assert await asyncio.wait_for(waiter, 3) == "Red, Blue"
        assert load_answers(settings.answers_file) == {"tools": "Red, Blue"}
    finally:
        if waiter and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await browser.kill()
