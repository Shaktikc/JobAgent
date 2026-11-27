from __future__ import annotations

import json
from pathlib import Path

from src.state import DEFAULT_SEARCH_QUERY
from src.tools import browser as browser_tools

from .common import _PAGE_HTML, _READ_STATE_JS, _render, _serve, _settings
from .common import pytestmark as pytestmark


async def test_task1_clicks_persistent_ai_button_once(tmp_path: Path) -> None:
    page_file = tmp_path / "task1.html"
    page_file.write_text(_render(_PAGE_HTML), encoding="utf-8")
    server, url = _serve(tmp_path, "task1.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        # ``_task1_on_page`` performs the initial navigation itself.
        outcome = await browser_tools._task1_on_page(
            page, url, DEFAULT_SEARCH_QUERY, _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_STATE_JS))
    finally:
        await browser.kill()
        server.shutdown()

    # Login gate is satisfied by the fixture's global nav.
    assert outcome.logged_in is True
    assert outcome.results_found is True

    # A visible entry control must not restart the completed AI search.
    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    assert observed["ai_clicks"] == 1

    # One initial search plus one repeat per click.
    assert observed["submit_clicks"] == 2
    assert outcome.results_count == 2

    # The Easy Apply filter was still selected afterwards.
    assert outcome.easy_apply_filter_selected is True
    assert observed["filter_pressed"] == "true"


