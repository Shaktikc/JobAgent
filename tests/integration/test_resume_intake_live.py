"""Opt-in live test for Task 15's intake description + move path.

It copies a real resume from the repository pool into a temporary
``resumes/new/`` folder, asks the real configured LLM to describe it, then
asserts the description mapping follows the file into ``resumes/``. The real
Task 3 match is run afterwards, so this also proves the moved resume joins the
candidate pool.

Enable it with a configured LLM and at least one resume in ``resumes/``::

    $env:AUTOJOB_RESUME_LIVE="1"
    uv run pytest tests/integration/test_resume_intake_live.py -s
"""

from __future__ import annotations

import os
import shutil

import pytest

from src.configuration import Settings, load_settings
from src.llm_model_routing import resume_llm_settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import ensure_resume, list_resume_files
from src.tools.resume_descriptions import description_for, load_descriptions

SETTINGS = load_settings()
SOURCE_FILES = list_resume_files(SETTINGS.resumes_dir)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_RESUME_LIVE")
        or not SOURCE_FILES
        or not resume_llm_settings(SETTINGS).configured,
        reason=(
            "set AUTOJOB_RESUME_LIVE=1, populate resumes/, and configure the LLM "
            "(OPENROUTER_API_KEY + AUTOJOB_RESUME_LLM_MODEL or AUTOJOB_LLM_MODEL) "
            "to run this live test"
        ),
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


async def test_intake_resume_is_described_moved_and_matched(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    source = SOURCE_FILES[0]
    intake_resume = intake / source.name
    shutil.copy2(source, intake_resume)

    settings = Settings(
        llm=SETTINGS.llm,
        data_dir=tmp_path,
        resumes_dir=main,
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
        resume_library_path=tmp_path / "resume_library.json",
    )
    outcome = await ensure_resume(
        JobDescription(
            title="Senior Python Backend Engineer",
            body="Python, AWS, Docker and PostgreSQL. 5+ years required.",
        ),
        main,
        settings,
        new_resumes_dir=intake,
    )

    moved = main / source.name
    assert not intake_resume.exists()
    assert moved.is_file()
    assert moved.read_bytes() == source.read_bytes()
    entries = load_descriptions(settings.resume_descriptions_file)
    description = description_for(entries, moved)
    assert description is not None and description.usable
    assert outcome.error == ""
    assert outcome.resumes_found == 1
    if outcome.selected_path is not None:
        assert outcome.selected_path == str(moved)
        assert outcome.rationale


async def test_moved_resume_is_attached_in_a_live_browser(tmp_path) -> None:
    """Task 15's moved file is accepted by Task 4's real CDP upload path."""
    pytest.importorskip("browser_use")

    from src.configuration import SessionSettings
    from src.state import Task4Outcome
    from src.tools import browser as browser_tools
    from src.tools.linkedin_easy_apply_fill.resume_attachment import _attach_resume
    from src.tools.resume_intake import process_new_resumes

    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    source = SOURCE_FILES[0]
    intake_resume = intake / source.name
    shutil.copy2(source, intake_resume)

    settings = Settings(
        session=SessionSettings(headless=True, post_click_wait_seconds=0),
        llm=SETTINGS.llm,
        data_dir=tmp_path / "data",
        resumes_dir=main,
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
        resume_library_path=tmp_path / "resume_library.json",
    )
    intake_outcome = await process_new_resumes(main, intake, settings)
    assert intake_outcome.ok is True
    moved = main / source.name
    assert moved.is_file() and not intake_resume.exists()

    form_file = tmp_path / "easy_apply.html"
    form_file.write_text(
        "<!doctype html><html><body>"
        '<div class="jobs-easy-apply-modal artdeco-modal" role="dialog">'
        "<h2>Apply to Acme</h2>"
        '<input id="resume-file" type="file">'
        "</div></body></html>",
        encoding="utf-8",
    )

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        task4 = Task4Outcome()
        await _attach_resume(page, browser, str(moved), settings, task4, lambda _m: None)
        uploaded_name = await page.evaluate(
            "() => { const f = document.querySelector('input[type=file]');"
            " return f && f.files.length ? f.files[0].name : ''; }"
        )
    finally:
        await browser.kill()

    assert task4.resume_attached is True
    assert task4.resume_selection == "uploaded"
    assert uploaded_name == moved.name
