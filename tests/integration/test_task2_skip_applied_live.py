"""Opt-in live-browser test for Task 6: skip job cards already marked "Applied".

It needs no LinkedIn account, no login, and no network: it serves a self-contained
LinkedIn-shaped results page from a local file and drives the **real** Task 2 code
path (:func:`_task2_on_page`) in a real Chromium window built by
:func:`build_browser`. This exercises what unit tests cannot: reading the card's
real ``innerText``, applying :func:`card_is_applied` to it, skipping the Applied
card without clicking it, then opening the first unapplied card and its Easy Apply
form — and stopping gracefully when every card is Applied.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_TASK2_LIVE="1"
    uv run pytest tests/integration/test_task2_skip_applied_live.py -s

Watch it with the window shown::

    $env:AUTOJOB_TASK2_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"
    uv run pytest tests/integration/test_task2_skip_applied_live.py -s

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_TASK2_LIVE"),
        reason="set AUTOJOB_TASK2_LIVE=1 to run the live Task 2 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _results_page(cards: list[tuple[str, str]]) -> str:
    """A LinkedIn-shaped results page with one card per ``(title, status)`` pair.

    The card's status line is what Task 6 reads; an empty ``status`` means the
    card shows no status text (treated as unapplied). Clicking a card reveals the
    details pane with its Easy Apply button; clicking that reveals the modal.
    """
    # Block-level elements (as on the real results page) make ``innerText``
    # whitespace-separated, so the card's status word "Applied" is read as its
    # own token by card_is_applied.
    lis = "\n".join(
        f'<li class="jobs-search-results__list-item" data-index="{i}">'
        f'<div class="base-search-card__title">{title}</div>'
        '<div class="base-search-card__subtitle">Acme</div>'
        f'<div class="job-search-card__snippet">{status}</div>'
        '<div class="job-search-card__snippet">Easy Apply</div></li>'
        for i, (title, status) in enumerate(cards)
    )
    # The JS block is written as a plain (non-f) string so its braces are literal.
    template = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<ul class="jobs-search__results-list">
__LIS__
</ul>
<div class="jobs-search__job-details--container" style="display:none">
  <button class="jobs-apply-button" aria-label="Easy Apply to the selected job at Acme">
    Easy Apply
  </button>
</div>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">Review your application. Easy Apply.</div>
</div>
<script>
  var details = document.querySelector('.jobs-search__job-details--container');
  var modal = document.querySelector('.jobs-easy-apply-modal');
  var applyBtn = details.querySelector('.jobs-apply-button');
  document.querySelectorAll('li.jobs-search-results__list-item').forEach(function (li) {
    li.addEventListener('click', function () {
      details.style.display = 'block';
      var title = (li.innerText || '').split('\\n')[0].trim() || 'the selected job';
      applyBtn.setAttribute('aria-label', 'Easy Apply to ' + title + ' at Acme');
      applyBtn.textContent = 'Easy Apply';
    });
  });
  applyBtn.addEventListener('click', function () {
    modal.style.display = 'block';
  });
</script>
</body></html>
"""
    return template.replace("__LIS__", lis)


def _settings(tmp_path: Path) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            post_click_wait_seconds=0.0,
            # The fixture reveals the details pane / modal synchronously on click.
            easy_apply_timeout_seconds=0.5,
            ask_human=False,
        ),
        data_dir=tmp_path / "data",
    )


def _read_page_state(page) -> dict:
    """What the fixture observed: which card was clicked and whether the modal opened."""
    payload = page.evaluate(
        "() => JSON.stringify({"
        "  modal_open: (() => {"
        "    const m = document.querySelector('.jobs-easy-apply-modal');"
        "    return m ? m.style.display === 'block' : false;"
        "  })(),"
        "  details_open: (() => {"
        "    const d = document.querySelector('.jobs-search__job-details--container');"
        "    return d ? d.style.display === 'block' : false;"
        "  })()"
        "})"
    )
    return json.loads(payload)


async def _run_task2_on_fixture(tmp_path: Path, cards: list[tuple[str, str]]) -> object:
    page_file = tmp_path / "task2.html"
    page_file.write_text(_results_page(cards), encoding="utf-8")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task2_on_page(
            page, _settings(tmp_path), lambda _m: None
        )
        return outcome
    finally:
        await browser.kill()


async def test_task2_skips_applied_card_and_opens_first_unapplied(tmp_path: Path) -> None:
    outcome = await _run_task2_on_fixture(
        tmp_path,
        [
            ("Backend Engineer", "Applied · 5 months ago"),
            ("Data Engineer", "Viewed 2 weeks ago"),
        ],
    )

    # The Applied card was skipped without being clicked.
    assert outcome.applied_jobs_skipped == 1
    assert outcome.applied_skipped_cards == [
        {"index": 0, "title": "Backend Engineer"}
    ]
    assert outcome.jobs_seen == 2
    # The first unapplied card was opened and its Easy Apply form reached.
    assert outcome.job_index == 1
    assert outcome.job_title == "Data Engineer"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_stops_when_every_card_is_applied(tmp_path: Path) -> None:
    outcome = await _run_task2_on_fixture(
        tmp_path,
        [
            ("Backend Engineer", "Applied · 5 months ago"),
            ("Data Engineer", "Applied 2 weeks ago"),
        ],
    )

    assert outcome.applied_jobs_skipped == 2
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert outcome.job_index is None
    assert "no unapplied job found" in outcome.notes


# Reproduces LinkedIn's AI/semantic results layout (origin=SEMANTIC_SEARCH_LANDING_PAGE),
# which the user hit: the job cards are div[role="button"], the details-pane apply
# button uses hashed CSS-in-JS classes (so it matches none of the ``jobs-apply-button``
# selectors) and is identifiable only by its label, and clicking a card re-renders the
# whole list — detaching every previously resolved card element. Card 0 is an external
# "Apply" job, so the agent must skip it and then click card 1 with a *fresh* handle.
_SEMANTIC_LAYOUT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<div id="list"></div>
<div class="details">
  <button id="apply" class="fmx1a fmx2b" type="button"
          aria-label="Apply to this job" style="display:none">Apply</button>
</div>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">Easy Apply. Review your application.</div>
</div>
<script>
  var apply = document.getElementById('apply');
  var modal = document.querySelector('.jobs-easy-apply-modal');
  var list = document.getElementById('list');
  var jobs = [
    { title: 'Backend Engineer', company: 'Acme',
      meta: 'Sydney, NSW (On-site) Actively reviewing applicants' },
    { title: 'Data Engineer', company: 'Beta', meta: 'Melbourne, VIC (Remote) Viewed' }
  ];
  function render() {
    // Re-rendering replaces the nodes, detaching any element handles a caller kept.
    list.innerHTML = jobs.map(function (j, i) {
      return '<div role="button" class="jobcard" data-index="' + i + '">'
        + j.title + ' ' + j.company + ' ' + j.meta + ' Easy Apply</div>';
    }).join('');
    list.querySelectorAll('.jobcard').forEach(function (card) {
      card.addEventListener('click', function () {
        var i = card.getAttribute('data-index');
        apply.style.display = 'inline-block';
        if (i === '0') {
          apply.setAttribute('aria-label', 'Apply to this job');
          apply.textContent = 'Apply';
        } else {
          apply.setAttribute('aria-label', 'Easy Apply to this job');
          apply.textContent = 'Easy Apply';
        }
        // Re-render after selecting, as LinkedIn does when it navigates the job.
        render();
      });
    });
  }
  render();
  apply.addEventListener('click', function () { modal.style.display = 'block'; });
</script>
</body></html>
"""


# The results page's tab title is the **search query** ("Full Stack Engineer Jobs"),
# not the open job's title. The pane check used to read document.title first, so
# every clicked card looked like it had not opened and was skipped ("the details
# pane did not open"). The pane's own heading must win.
_SEARCH_TITLE_JOB = (
    "Sr Full Stack Engineer - AI, LLM & Intelligent Document Processing (Verified job)"
)
_SEARCH_TITLE_LAYOUT_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Full Stack Engineer Jobs | LinkedIn</title></head>
<body>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">__TITLE__</div>
    <div class="base-search-card__subtitle">Acme</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
</ul>
<div class="jobs-search__job-details--container" style="display:none">
  <h1 class="job-details-jobs-unified-top-card__job-title"></h1>
  <button class="jobs-apply-button" aria-label="Easy Apply to this job">Easy Apply</button>
</div>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">Review your application. Easy Apply.</div>
</div>
<script>
  var details = document.querySelector('.jobs-search__job-details--container');
  var heading = details.querySelector('h1');
  var applyBtn = details.querySelector('.jobs-apply-button');
  var modal = document.querySelector('.jobs-easy-apply-modal');
  document.querySelectorAll('li.jobs-search-results__list-item').forEach(function (li) {
    li.addEventListener('click', function () {
      details.style.display = 'block';
      heading.textContent = (li.innerText || '').split('\\n')[0].trim();
      applyBtn.setAttribute('aria-label', 'Easy Apply to ' + heading.textContent);
    });
  });
  applyBtn.addEventListener('click', function () { modal.style.display = 'block'; });
</script>
</body></html>
""".replace("__TITLE__", _SEARCH_TITLE_JOB)


async def test_task2_reads_the_pane_heading_not_the_search_page_title(tmp_path: Path) -> None:
    page_file = tmp_path / "search_title_layout.html"
    page_file.write_text(_SEARCH_TITLE_LAYOUT_HTML, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task2_on_page(page, settings, lambda _m: None)
    finally:
        await browser.kill()

    # The clicked card opened even though the tab title is the search query.
    assert outcome.job_index == 0
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True
    assert "Sr Full Stack Engineer" in outcome.job_title


async def test_task2_semantic_layout_uses_label_and_fresh_handles(tmp_path: Path) -> None:
    """The label-only apply button is found and the re-rendered list is re-read."""
    page_file = tmp_path / "semantic_layout.html"
    page_file.write_text(_SEMANTIC_LAYOUT_HTML, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task2_on_page(page, settings, lambda _m: None)
    finally:
        await browser.kill()

    assert outcome.jobs_seen == 2
    # The external card 0 was skipped, then card 1 was opened with a fresh handle.
    assert outcome.skipped_jobs == 1
    assert "Data Engineer" in outcome.job_title
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


# Reproduces BUG-068: an overlay swallows the coordinate CDP click on the
# next-page control; the control's own DOM ``click()`` must still advance.
_PAGINATION_LAYOUT_HTML = """<!doctype html><meta charset="utf-8">
<ul class="jobs-search__results-list" id="list">
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">Backend Engineer</div>
    <div class="job-search-card__snippet">Applied · Easy Apply</div>
  </li>
</ul>
<div id="pager">
  <button type="button" aria-label="Page 1" aria-current="true">1</button>
  <button type="button" aria-label="Page 2" aria-current="false">2</button>
  <button type="button"><span>Next</span></button>
</div>
<div id="scrim" style="position:fixed;inset:0;z-index:2147483600"></div>
<script>
  var list = document.getElementById('list'), scrim = document.getElementById('scrim'), page = 1;
  function goToPageTwo() {
    page = 2;
    scrim.style.display = 'none';
    list.innerHTML = '<li class="jobs-search-results__list-item">'
      + '<div class="base-search-card__title">QA Engineer</div>'
      + '<div class="job-search-card__snippet">Viewed · Easy Apply</div></li>';
  }
  document.querySelectorAll('#pager button').forEach(function (b) {
    b.addEventListener('click', function () {
      var isNext = b.textContent.trim() === 'Next';
      if (page === 1 && (b.getAttribute('aria-label') === 'Page 2' || isNext)) {
        goToPageTwo();
      }
    });
  });
</script>
"""


async def test_go_to_next_page_survives_a_swallowed_cdp_click(tmp_path, monkeypatch) -> None:
    """BUG-068: the next-page control still advances when the CDP click is eaten."""
    import asyncio

    from src.tools import linkedin_pagination
    from src.tools.linkedin_pagination import (
        _first_element,
        go_to_next_page,
        pick_next_page_control,
        read_pagination,
    )
    monkeypatch.setattr(linkedin_pagination, "_PAGE_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(linkedin_pagination, "_PAGE_POLL_SECONDS", 0.05)
    page_file = tmp_path / "pagination.html"
    page_file.write_text(_PAGINATION_LAYOUT_HTML, encoding="utf-8")
    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        info = await read_pagination(page)
        control = pick_next_page_control(info["controls"], info["current"])
        assert control is not None and control["label"] == "Next"
        element = await _first_element(page, [f'[data-autojob-page="{control["marker"]}"]'])
        await element.click()  # the scrim swallows this coordinate CDP click
        await asyncio.sleep(0.3)
        still_page_one = int(
            await page.evaluate("() => document.querySelectorAll('#list li').length")
        )
        advanced = await go_to_next_page(page, settings, lambda _m: None)
        title = str(await page.evaluate("() => document.querySelector('#list li').innerText"))
    finally:
        await browser.kill()

    assert still_page_one == 1  # the premise: the CDP click did not advance
    assert advanced is True
    assert "QA Engineer" in title
