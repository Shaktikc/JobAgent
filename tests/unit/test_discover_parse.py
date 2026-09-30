"""Unit tests for partial `discovery` (Task 5): read one job page, detect Easy Apply.

No network, no browser: every case parses a saved HTML fixture in
``tests/fixtures/`` (SPEC.md §6). The Playwright fetch path is exercised manually.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.nodes.discover import NotEasyApplyError, extract_job
from src.state import JobState
from src.tools import linkedin

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

EASY_APPLY_HTML = (FIXTURES / "job_easy_apply.html").read_text(encoding="utf-8")
EXTERNAL_APPLY_HTML = (FIXTURES / "job_external_apply.html").read_text(encoding="utf-8")

EASY_APPLY_URL = "https://www.linkedin.com/jobs/view/4012345678/"
EXTERNAL_APPLY_URL = "https://www.linkedin.com/jobs/view/4099999999/"


# --- URL / job id -----------------------------------------------------------


def test_job_id_from_view_url() -> None:
    assert linkedin.job_id_from_url(EASY_APPLY_URL) == "4012345678"


def test_job_id_from_search_url_current_job_id() -> None:
    url = "https://www.linkedin.com/jobs/search/?keywords=data&currentJobId=4012345678&refId=x"

    assert linkedin.job_id_from_url(url) == "4012345678"


def test_job_id_from_url_rejects_unknown_url() -> None:
    with pytest.raises(ValueError, match="job id"):
        linkedin.job_id_from_url("https://www.linkedin.com/feed/")


# --- parsing ----------------------------------------------------------------


def test_parse_job_page_extracts_title_company_description() -> None:
    details = linkedin.parse_job_page(EASY_APPLY_HTML, url=EASY_APPLY_URL)

    assert details.title == "Senior Data Analyst"
    assert details.company == "Acme Analytics"
    assert "Senior Data Analyst" in details.description
    assert "5+ years of SQL" in details.description
    assert "Python and dashboards" in details.description


def test_parse_job_page_preserves_url_and_job_id() -> None:
    details = linkedin.parse_job_page(EASY_APPLY_HTML, url=EASY_APPLY_URL)

    assert details.url == EASY_APPLY_URL
    assert details.job_id == "4012345678"


def test_detect_easy_apply_true_for_easy_apply_fixture() -> None:
    assert linkedin.detect_easy_apply(EASY_APPLY_HTML) is True


def test_detect_easy_apply_false_for_external_fixture() -> None:
    assert linkedin.detect_easy_apply(EXTERNAL_APPLY_HTML) is False


def test_parse_job_page_does_not_leak_location_into_company() -> None:
    details = linkedin.parse_job_page(EASY_APPLY_HTML, url=EASY_APPLY_URL)

    assert "Boston" not in details.company


def test_parse_unknown_page_leaves_fields_empty() -> None:
    details = linkedin.parse_job_page("<html><body><p>Nothing here</p></body></html>")

    assert details.title == ""
    assert details.company == ""
    assert details.description == ""
    assert details.easy_apply is False


# --- node behaviour: Easy Apply gate ---------------------------------------


def test_extract_job_returns_job_state_for_easy_apply() -> None:
    state = extract_job(EASY_APPLY_HTML, url=EASY_APPLY_URL)

    assert isinstance(state, dict)
    assert state["job_id"] == "4012345678"
    assert state["title"] == "Senior Data Analyst"
    assert state["company"] == "Acme Analytics"
    assert state["url"] == EASY_APPLY_URL
    assert state["easy_apply"] is True
    # JobState is the emitted contract for later tasks.
    assert JobState.__annotations__.keys() >= state.keys()


def test_extract_job_raises_typed_error_for_non_easy_apply() -> None:
    with pytest.raises(NotEasyApplyError, match="Easy Apply"):
        extract_job(EXTERNAL_APPLY_HTML, url=EXTERNAL_APPLY_URL)


def test_not_easy_apply_error_names_the_job() -> None:
    with pytest.raises(NotEasyApplyError, match="4099999999"):
        extract_job(EXTERNAL_APPLY_HTML, url=EXTERNAL_APPLY_URL)
