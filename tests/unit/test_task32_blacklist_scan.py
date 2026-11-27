"""Task 32: the results scanner skips blacklisted companies (offline).

Drives :func:`_scan_page` with fake cards; the browser helpers it calls are
monkeypatched at the module that calls them.
"""

from __future__ import annotations

import pytest

from src.configuration import SessionSettings, Settings
from src.state import JobDescription, Task2Outcome
from src.tools import company_blacklist as cb
from src.tools import linkedin_company_skip as skip
from src.tools import linkedin_job_selection as jobsel
from src.tools.linkedin_best_matching_resume import description_reader


class _Card:
    def __init__(self, title: str, company: str, *, shown: str = "", job_id: str = "") -> None:
        self.title = title
        self.company = company
        self.label = f"{title}\n{shown}\nRemote\nEasy Apply" if shown else f"{title}\nRemote"
        self.shown = shown
        self.job_id = job_id

    async def evaluate(self, js: str, *args):
        if "company-name" in js:
            return self.shown
        return self.label


class _Page:
    def __init__(self, cards: list[_Card]) -> None:
        self.cards = cards
        self.open = None


@pytest.fixture
def scan(monkeypatch):
    """Patch the scanner's browser helpers; return ``run(cards, blacklist)``."""
    events: dict = {"opened": [], "apply_checked": [], "pane_reads": 0}

    async def read_cards(page):
        return list(page.cards)

    async def label(card):
        return card.label

    async def open_card(page, card, title, settings, notify):
        page.open = card
        events["opened"].append(card.title)
        return True, title

    async def apply_button(page, settings):
        events["apply_checked"].append(page.open.title)
        return object(), "Easy Apply"

    async def card_id(card):
        return card.job_id

    async def record_scan(page, card, key):
        return None

    async def describe(page):
        events["pane_reads"] += 1
        return JobDescription(title=page.open.title, company=page.open.company, body="x")

    from src.tools.token_usage import applications

    monkeypatch.setattr(jobsel, "read_job_cards", read_cards)
    monkeypatch.setattr(jobsel, "_wait_for_cards", read_cards)
    monkeypatch.setattr(jobsel, "_element_label", label)
    monkeypatch.setattr(jobsel, "open_job_card", open_card)
    monkeypatch.setattr(jobsel, "wait_for_job_apply_button", apply_button)
    monkeypatch.setattr(jobsel, "read_card_id", card_id)
    monkeypatch.setattr(applications, "record_scan", record_scan)
    monkeypatch.setattr(description_reader, "read_job_description", describe)

    async def run(cards, blacklist: list[str], tried: set[str] | None = None):
        monkeypatch.setattr(skip, "get_blacklist", lambda: cb.parse_blacklist(blacklist))
        settings = Settings(session=SessionSettings(headless=True, skip_applied=True))
        outcome = Task2Outcome()
        page = _Page(cards)
        result = await jobsel._scan_page(
            page, settings, lambda _m: None, outcome, tried if tried is not None else set(),
            set(), None, open_form=False,
        )
        return result, outcome

    return run, events


async def test_blacklisted_card_is_never_clicked_and_next_job_is_selected(scan) -> None:
    run, events = scan
    cards = [_Card("Engineer", "Acme", shown="Acme"), _Card("Engineer", "Globex", shown="Globex")]
    result, outcome = await run(cards, ["acme"])
    assert result.selected
    assert events["opened"] == ["Engineer"] and events["apply_checked"] == ["Engineer"]
    assert outcome.blacklisted_jobs_skipped == 1
    assert outcome.blacklisted_skipped_cards == [
        {"index": 0, "title": "Engineer", "company": "Acme"}
    ]
    # Globex's same-title posting stayed eligible and was the one selected.
    assert outcome.job_index == 1


async def test_similar_company_name_stays_eligible(scan) -> None:
    run, _events = scan
    result, outcome = await run([_Card("Engineer", "Acme Labs", shown="Acme Labs")], ["Acme"])
    assert result.selected and outcome.blacklisted_jobs_skipped == 0


async def test_empty_blacklist_leaves_selection_unchanged(scan) -> None:
    run, events = scan
    result, outcome = await run([_Card("Engineer", "Acme", shown="Acme")], [])
    assert result.selected and outcome.job_index == 0
    assert events["pane_reads"] == 0  # no extra pane read without a list


async def test_every_card_blacklisted_selects_nothing(scan) -> None:
    run, events = scan
    cards = [_Card("A", "Acme", shown="Acme"), _Card("B", "Globex", shown="GLOBEX")]
    result, outcome = await run(cards, ["acme", "globex"])
    assert not result.selected and events["opened"] == []
    assert outcome.blacklisted_jobs_skipped == 2
    assert cb.only_blacklisted_jobs_left(outcome)


async def test_pane_company_is_checked_before_easy_apply(scan) -> None:
    """A card without a company is opened, but its pane match never reaches Easy Apply."""
    run, events = scan
    cards = [_Card("Engineer", "Acme", job_id="1"), _Card("Engineer", "Globex", job_id="2")]
    tried: set[str] = set()
    result, outcome = await run(cards, ["acme"], tried)
    assert result.selected and outcome.job_index == 1
    assert events["opened"] == ["Engineer", "Engineer"]
    assert events["apply_checked"] == ["Engineer"]  # only Globex's
    assert outcome.blacklisted_skipped_cards[0]["company"] == "Acme"
    assert "job:1" in tried


def test_unfinished_scan_is_not_a_clean_blacklist_end() -> None:
    outcome = Task2Outcome(blacklisted_jobs_skipped=2, notes="the results list did not change")
    assert not cb.only_blacklisted_jobs_left(outcome)
    assert not cb.only_blacklisted_jobs_left(Task2Outcome())
    selected = Task2Outcome(blacklisted_jobs_skipped=1, job_selected=True)
    assert not cb.only_blacklisted_jobs_left(selected)
