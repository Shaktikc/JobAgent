"""Opt-in live-browser test for Task 3's job-description read.

It needs no LinkedIn account, no login, and no network: it serves LinkedIn-shaped
job pages from local files and drives the **real** :func:`read_job_description`
query in a real Chromium window built by :func:`build_browser`. This exercises what
the fake-page unit tests cannot: the actual CSS selectors and the class-agnostic
fallback against the several layouts LinkedIn serves for the same job.

The regression it guards: the read used to only know the classic two-pane
selectors, so on the newer full-page job view (``.description__text`` /
``.show-more-less-html__markup``) and on the AI/semantic job view (hashed
CSS-in-JS classes, no stable selector) it returned an empty description. The LLM
then answered "none", the agent asked the human for a resume, and the
remembered-resume library filled with empty job profiles.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_TASK3_LIVE="1"
    uv run pytest tests/integration/test_job_description_live.py -s

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools.linkedin_best_matching_resume import read_job_description

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_TASK3_LIVE"),
        reason="set AUTOJOB_TASK3_LIVE=1 to run the live Task 3 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

# The classic two-pane results page.
_CLASSIC = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="jobs-search__job-details--container">
  <h1 class="job-details-jobs-unified-top-card__job-title">Backend Engineer</h1>
  <div class="job-details-jobs-unified-top-card__company-name">Acme</div>
  <div class="job-details-jobs-unified-top-card__bullet">Remote</div>
  <div class="jobs-description__content">
    <p>We build services with Python, AWS and Docker. 5+ years required.</p>
  </div>
</div>
</body></html>"""

# LinkedIn's newer full-page job view (BEM + utility classes).
_BEM = """<!doctype html><html><head><meta charset="utf-8">
<title>Senior Software Engineer | LinkedIn</title></head><body>
<main>
  <h1 class="top-card-layout__title">Senior Software Engineer</h1>
  <a class="topcard__org-name-link">Respondent</a>
  <span class="topcard__flavor--bullet">Sydney, New South Wales, Australia</span>
  <div class="description__text description__text--rich">
    <section class="show-more-less-html">
      <div class="show-more-less-html__markup">
        <p>Full stack expertise: our stack includes TypeScript, Node.js, React,
           AWS and MongoDB.</p>
      </div>
    </section>
  </div>
</main>
</body></html>"""

# The AI/semantic job view: every class is hashed CSS-in-JS, so no stable
# selector matches the description container.
_HASHED = """<!doctype html><html><head><meta charset="utf-8">
<title>Senior Full Stack Engineer | LinkedIn</title></head><body>
<main>
  <div class="ckym8e ckym8d">
    <h1 class="ckyjzz">Senior Full Stack Engineer</h1>
  </div>
  <div class="ckya5p ckymt4">
    <span class="ckygvk">Respondent</span><span class="ckyglc">Sydney</span>
  </div>
  <div class="ckym4l ckym4k">
    <p>We're looking for a Senior Engineer who's excited to build products
       that customers genuinely love.</p>
    <p>Full stack expertise: strong experience across both front-end and
       back-end. Our stack includes TypeScript, Node.js, React, AWS and
       MongoDB.</p>
    <ul><li>Build robust and secure APIs.</li><li>Work at the edge of AI.</li></ul>
  </div>
</main>
</body></html>"""


# The AI/semantic job view inside LinkedIn's global chrome. Both the tab title
# and a global-nav heading say "0 notifications"; the job title must still come
# from the details pane. The old global ``h1``/``h2`` fallback returned the nav
# text, so the LLM matched a Full Stack Engineer job labelled "0 notifications".
_GLOBAL_NAV = """<!doctype html><html><head><meta charset="utf-8">
<title>0 notifications | LinkedIn</title></head><body>
<header class="global-nav">
  <h2>0 notifications</h2>
  <h1>LinkedIn</h1>
</header>
<main>
  <div class="ckym8e ckym8d">
    <h1 class="ckyjzz">Senior Full Stack Engineer</h1>
  </div>
  <div class="ckym4l ckym4k">
    <p>We're looking for a Senior Engineer to build products customers love.</p>
    <p>Our stack includes TypeScript, Node.js, React, AWS and MongoDB.</p>
  </div>
</main>
</body></html>"""


def _settings(tmp_path: Path) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(headless=headless, clean_stale_profile=False),
        data_dir=tmp_path / "data",
        resumes_dir=tmp_path / "resumes",
    )


@pytest.mark.parametrize(
    ("name", "html", "title", "needle"),
    [
        ("classic", _CLASSIC, "Backend Engineer", "Python"),
        ("bem", _BEM, "Senior Software Engineer", "MongoDB"),
        ("hashed", _HASHED, "Senior Full Stack Engineer", "TypeScript"),
        ("global-nav", _GLOBAL_NAV, "Senior Full Stack Engineer", "TypeScript"),
    ],
)
async def test_reads_the_description_across_linkedin_layouts(
    tmp_path: Path, name: str, html: str, title: str, needle: str
) -> None:
    page_file = tmp_path / f"{name}.html"
    page_file.write_text(html, encoding="utf-8")

    browser = browser_tools.build_browser(_settings(tmp_path))
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        description = await read_job_description(page)
    finally:
        await browser.kill()

    assert description.is_read is True, f"{name}: nothing was read"
    assert description.title == title
    assert needle in description.body
