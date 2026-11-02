"""Task 21: SDUI helper text must never hide a question's visible asterisk."""

import json
import os

import pytest
import pytest_asyncio

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_REQUIRED_LIVE"), reason="set AUTOJOB_REQUIRED_LIVE=1"
)

SALARY = "What's your expected annual base salary?*"
EXPERIENCE = "How many years' experience do you have as a software engineer?*"
NOTICE = "How many weeks' notice do you give your current employer? *"


@pytest_asyncio.fixture
async def page(tmp_path):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=True)))
    await browser.start()
    try:
        yield await browser.new_page()
    finally:
        await browser.kill()


def question(heading, control, *, helper="0/20", testid=True):
    helper_attr = ' data-testid="text-input-helper-text"' if testid else ""
    return (
        f'<div><p>{heading}</p><div><div>{control}</div>'
        f'<div{helper_attr}><div><p aria-live="polite">'
        f'<span aria-hidden="true">{helper}</span>'
        '<span>0 of 20 characters</span></p></div></div></div></div>'
    )


@pytest.mark.parametrize("testid", [True, False])
@pytest.mark.parametrize("source", ["stored", "human"])
async def test_starred_questions_reach_answers_instead_of_becoming_character_counters(
    page, tmp_path, testid, source
):
    body = (
        question(SALARY, '<input id="salary" aria-label="Expected annual salary" required>',
                 testid=testid)
        + question(EXPERIENCE, '<textarea id="experience" required></textarea>', testid=testid)
        + question(NOTICE, '<select id="notice"><option value="">Select an option</option>'
                   '<option value="2">2</option></select>', testid=testid)
        + question("Additional details", '<input id="optional" required value="Keep this">',
                   helper="9/20", testid=testid)
    )
    fixture = tmp_path / "starred_text_questions.html"
    fixture.write_text(
        '<dialog open><h2>Apply to Example</h2>' + body
        + '<button type="button">Submit application</button></dialog>', encoding="utf-8"
    )
    await page.goto(fixture.as_uri())
    opened, _, fields, _ = await read_form(page)
    assert opened
    assert [(field["question"], field["required"]) for field in fields] == [
        (SALARY, True), (EXPERIENCE, True), (NOTICE, True), ("Additional details", False),
    ]

    calls = []
    asked = []
    expected = {SALARY: "120000", EXPERIENCE: "4", NOTICE: "2"}

    async def chooser(question, kind, options):
        calls.append(question)
        return QuestionDecision(
            question=question, answer=expected[question] if source == "stored" else None,
        )

    async def ask(question, field):
        asked.append(question)
        assert field["required"]
        return expected[question]

    known, filled, unknown, records = await _fill_step(
        page, fields, {}, Settings(data_dir=tmp_path / "answers"), chooser=chooser, ask=ask,
    )
    values = json.loads(await page.evaluate("""() => JSON.stringify(
      ['salary','experience','notice','optional'].map(id => document.getElementById(id).value)
    )"""))
    assert values == ["120000", "4", "2", "Keep this"]
    assert calls == [SALARY, EXPERIENCE, NOTICE]
    assert asked == ([SALARY, EXPERIENCE, NOTICE] if source == "human" else [])
    assert (known, filled, unknown) == (3, 3, [])
    assert all(record.required and record.filled for record in records)


async def test_trailing_helper_asterisks_cannot_require_optional_or_unlabelled_fields(
    page, tmp_path
):
    fixture = tmp_path / "optional_helper_asterisks.html"
    fixture.write_text(
        '<dialog open><h2>Apply to Example</h2>'
        + question("Additional details", '<input id="optional" required>', helper="0/20 *")
        + '<div><input id="unlabelled" required><p>Helper text *</p></div>'
        + '<button type="button">Submit application</button></dialog>', encoding="utf-8"
    )
    await page.goto(fixture.as_uri())
    _, _, fields, _ = await read_form(page)
    assert [(field["question"], field["required"]) for field in fields] == [
        ("Additional details", False), ("", False),
    ]
