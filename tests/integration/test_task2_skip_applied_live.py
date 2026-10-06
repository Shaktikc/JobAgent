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
