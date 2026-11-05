"""Opt-in real LinkedIn query check; stops before opening any application.

Run with AUTOJOB_TASK18_LIVE=1. Uses the dedicated JobAgent login profile.
"""

import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_TASK18_LIVE"), reason="opt-in real LinkedIn check"
)


def test_startup_query_reaches_linkedin(monkeypatch):
    import src.main as cli
    from src.configuration import load_settings
    from src.tools.browser import _detach_session, build_browser
    from src.tools.linkedin_search import search_box
    from src.tools.linkedin_search.orchestrator import _task1_on_page

    typed_values = []
    find_input = search_box.find_jobs_search_input

    class ObservedInput:
        def __init__(self, field):
            self.field = field

        def __getattr__(self, name):
            return getattr(self.field, name)

        async def fill(self, query):
            await self.field.fill(query)
            value = await self.field.evaluate("() => this.value")
            print(f"Input value after fill: {value!r}", flush=True)
            typed_values.append(value)

    async def observe_input(page):
        field = await find_input(page)
        return ObservedInput(field) if field is not None else None

    monkeypatch.setattr(search_box, "find_jobs_search_input", observe_input)
    prompts = []
    answers = iter(["  data   engineer  ", "1"])

    def answer(prompt):
        prompts.append(prompt)
        value = next(answers)
        print(prompt + value)
        return value

    async def search_only(state, config):
        assert state["search_query"] == "data engineer"
        settings = load_settings()
        settings.session.login_timeout_seconds = 60
        cdp_url = os.environ.get("AUTOJOB_TASK18_CDP_URL")
        if cdp_url:
            from browser_use import Browser
            session = Browser(cdp_url=cdp_url, keep_alive=True)
        else:
            session = build_browser(settings)
        try:
            await session.start()
            page = await session.new_page()
            outcome = await _task1_on_page(
                page, state["url"], state["search_query"], settings, print,
                date_range=state["date_range"],
            )
            print(outcome.model_dump())
            assert outcome.logged_in
            assert outcome.results_found
            assert parse_qs(urlparse(outcome.page_url).query)["keywords"] == ["data engineer"]
            assert typed_values, "the real search input was never filled"
            assert all(value == "data engineer" for value in typed_values)
            print(f"Verified real search input values: {typed_values}")
            return {**state, "status": "done", "task1": outcome}
        finally:
            await _detach_session(session)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(cli, "graph", SimpleNamespace(ainvoke=search_only))
    assert cli.main(["--no-dry-run", "--submission-mode", "manual"]) == 0
    assert prompts[0].startswith("What job")
    assert prompts[1].startswith("Choose 1 or 2")
