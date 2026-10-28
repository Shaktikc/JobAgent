"""Task 16: strict resume matching and safe skipping of unmatched jobs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.configuration import SessionSettings, Settings
from src.state import ApplyState, JobDescription, Task2Outcome, Task3Outcome, Task16Outcome
from src.tools.linkedin_best_matching_resume import ensure_resume
from src.tools.linkedin_resume_gate import (
    close_easy_apply_form,
    normalize_title,
    record_skip,
    should_skip_job,
    skip_record,
)
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    ResumeMatch,
)
from src.tools.resume_library import remember_resume


def _settings(tmp_path: Path, *, strict: bool = True, **session) -> Settings:
    session.setdefault("require_resume_match", strict)
    session.setdefault("ask_poll_seconds", 0.01)
    return Settings(
        session=SessionSettings(**session),
        data_dir=tmp_path,
        resumes_dir=tmp_path,
        resume_library_path=tmp_path / "resume_library.json",
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
    )


def _describer(summary: str = "profile"):
    async def describe(path):
        return ResumeDescription(summary=summary)

    return describe


def _picks(path: str | None, fit: str = "strong", rationale: str = "reason"):
    async def pick(_job_description, _candidates):
        return ResumeMatch(selected_path=path, fit=fit, rationale=rationale)

    return pick


def _raises(message: str = "the LLM call failed: boom"):
    async def pick(_job_description, _candidates):
        raise ResumeDescriptionError(message)

    return pick


# --- the pure gate ----------------------------------------------------------


def test_should_skip_only_in_strict_mode(tmp_path) -> None:
    strong = Task3Outcome(selected_path="r.txt", fit="strong")
    partial = Task3Outcome(no_match=True, fit="partial")
    missing = Task3Outcome(selected_path="r.txt", fit="")

    assert should_skip_job(strong, _settings(tmp_path)) is False
    assert should_skip_job(partial, _settings(tmp_path)) is True
    assert should_skip_job(missing, _settings(tmp_path)) is True
    # Legacy mode never skips on a weak match (Task 3.1's fallbacks stay in charge).
    assert should_skip_job(partial, _settings(tmp_path, strict=False)) is False


def test_should_skip_never_hides_a_match_error(tmp_path) -> None:
    failed = Task3Outcome(error="match: the LLM is not configured")
    assert should_skip_job(failed, _settings(tmp_path)) is False


def test_skip_record_and_counter() -> None:
    outcome = Task3Outcome(
        job_description=JobDescription(title="Data Analyst", company="Acme"),
        fit="partial",
        rationale="only some skills overlap",
    )
    task2 = Task2Outcome(job_index=4, job_title="Data Analyst")

    record = skip_record(outcome, task2)
    assert record.index == 4
    assert record.title == "Data Analyst"
    assert record.company == "Acme"
    assert record.fit == "partial"
    assert record.rationale == "only some skills overlap"

    task16 = record_skip(None, outcome, task2)
    assert task16.enabled is True
    assert task16.jobs_skipped == 1
    assert task16.skipped[0].title == "Data Analyst"


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("  Senior   Data   Analyst ") == "senior data analyst"


# --- ensure_resume under strict matching ------------------------------------


async def test_strict_mode_selects_a_strong_match(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python AWS", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks(str(tmp_path / "python.txt"), "strong"),
    )

    assert outcome.error == ""
    assert outcome.no_match is False
    assert outcome.selected_path == str(tmp_path / "python.txt")
    assert outcome.fit == "strong"


async def test_strict_mode_skips_a_partial_match(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python AWS", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Data Analyst", body="SQL reporting"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks(str(tmp_path / "python.txt"), "partial", "not the same role"),
    )

    assert outcome.error == ""
    assert outcome.no_match is True
    assert outcome.selected_path is None
    assert outcome.fit == "partial"
    assert "not a strong match" in outcome.notes


async def test_strict_mode_skips_when_the_fit_is_missing(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python AWS", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks(str(tmp_path / "python.txt"), ""),
    )

    assert outcome.no_match is True
    assert outcome.selected_path is None


async def test_strict_mode_never_asks_or_reuses_a_remembered_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")
    remembered = tmp_path / "cloud.txt"
    remembered.write_text("cloud engineer", encoding="utf-8")
    settings = _settings(tmp_path)
    remember_resume(
        settings.resume_library_file,
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        str(remembered),
    )
    asked: list[str] = []

    async def asker(page, settings, notify):
        asked.append("asked")
        return "resume.txt", b"python"

    outcome = await ensure_resume(
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        tmp_path,
        settings,
        page=object(),
        asker=asker,
        describer=_describer(),
        matcher=_picks(str(tmp_path / "pastry.txt"), "partial"),
    )

    assert outcome.no_match is True
    assert outcome.selected_path is None
    assert outcome.asked_human is False
    assert outcome.reused_from_library == ""
    assert asked == []
    assert "not a strong match" in outcome.notes


async def test_legacy_mode_still_reuses_a_remembered_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")
    remembered = tmp_path / "cloud.txt"
    remembered.write_text("cloud engineer", encoding="utf-8")
    settings = _settings(tmp_path, strict=True)  # strict setting, explicit override
    remember_resume(
        settings.resume_library_file,
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        str(remembered),
    )

    outcome = await ensure_resume(
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        tmp_path,
        settings,
        allow_fallback=True,
        describer=_describer(),
        matcher=_picks(None, "none"),
    )

    assert outcome.no_match is True
    assert outcome.selected_path == str(remembered)
    assert outcome.reused_from_library == str(remembered)


async def test_strict_mode_keeps_an_llm_error_as_a_failure(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_raises(),
    )

    assert outcome.error
    assert outcome.selected_path is None
    assert should_skip_job(outcome, _settings(tmp_path)) is False


# --- the match node records the skip ---------------------------------------


def test_match_node_records_a_strict_skip(tmp_path, monkeypatch) -> None:
    import src.tools.linkedin_best_matching_resume as resume_tools
    from src.nodes.match import match as match_node

    async def fake_ensure(description, resumes_dir, settings, page=None, notify=None, **kwargs):
        return Task3Outcome(
            job_description=description,
            resumes_dir=str(resumes_dir),
            resumes_found=1,
            no_match=True,
            fit="partial",
            rationale="the resume is a different role",
        )

    monkeypatch.setattr(resume_tools, "ensure_resume", fake_ensure)
    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        task2=Task2Outcome(job_index=2, job_title="Data Analyst"),
        job_description=JobDescription(title="Data Analyst", company="Acme"),
    )

    result = asyncio.run(match_node(state))

    assert result["status"] == "skipped"
    assert "errors" not in result
    assert result["task16"].jobs_skipped == 1
    assert result["task16"].skipped[0].title == "Data Analyst"
    assert result["skipped_titles"] == ["data analyst"]
    assert result["task3"].fit == "partial"


# --- closing the skipped form ----------------------------------------------


class _FakeButton:
    def __init__(self, page, label: str) -> None:
        self.page = page
        self.label = label
        self.clicked = False

    async def get_attribute(self, name: str):
        return self.label if name == "aria-label" else None

    async def evaluate(self, _js: str):
        return self.label

    async def click(self) -> None:
        self.clicked = True
        self.page.clicked.append(self.label)
        if self.label.lower() in {"dismiss", "close", "x", "discard", "discard application"}:
            self.page.open = False


class _FakeClosePage:
    def __init__(self, buttons: list[str], *, open_modal: bool = True) -> None:
        self.open = open_modal
        self.buttons = [_FakeButton(self, label) for label in buttons]
        self.clicked: list[str] = []

    async def evaluate(self, js: str, *args):
        if "findApplyRoot" in js:
            return json.dumps(
                {
                    "open": self.open,
                    "text": "Easy Apply Apply to Acme Next" if self.open else "",
                }
            )
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        if selector == "div.jobs-easy-apply-modal button":
            return list(self.buttons)
        return []


def test_close_easy_apply_form_clicks_dismiss_only(monkeypatch, tmp_path) -> None:
    import src.tools.linkedin_resume_gate as gate

    monkeypatch.setattr(gate, "_CLOSE_POLL_SECONDS", 0)
    page = _FakeClosePage(["Dismiss", "Next", "Submit application"])

    closed = asyncio.run(close_easy_apply_form(page, _settings(tmp_path)))

    assert closed is True
    assert page.clicked == ["Dismiss"]
    assert "Submit application" not in page.clicked


def test_close_easy_apply_form_handles_an_already_closed_form(tmp_path) -> None:
    page = _FakeClosePage(["Dismiss"], open_modal=False)
    assert asyncio.run(close_easy_apply_form(page, _settings(tmp_path))) is True
    assert page.clicked == []


def test_close_easy_apply_form_uses_discard_when_that_is_all_that_is_left(
    monkeypatch, tmp_path
) -> None:
    import src.tools.linkedin_resume_gate as gate

    monkeypatch.setattr(gate, "_CLOSE_POLL_SECONDS", 0)
    page = _FakeClosePage(["Discard", "Cancel"])

    closed = asyncio.run(close_easy_apply_form(page, _settings(tmp_path)))

    assert closed is True
    assert page.clicked == ["Discard"]


def test_close_easy_apply_form_reports_a_stuck_form(monkeypatch, tmp_path) -> None:
    import src.tools.linkedin_resume_gate as gate

    monkeypatch.setattr(gate, "_CLOSE_POLL_SECONDS", 0)
    page = _FakeClosePage(["Next"])

    assert asyncio.run(close_easy_apply_form(page, _settings(tmp_path))) is False
    assert page.clicked == []


def test_close_easy_apply_form_is_a_noop_when_no_form_is_open(tmp_path) -> None:
    """The gate helper is mode-independent; only the caller decides to skip."""
    page = _FakeClosePage([], open_modal=False)
    assert asyncio.run(close_easy_apply_form(page, _settings(tmp_path, strict=False))) is True
    assert page.clicked == []


def test_task16_outcome_defaults_are_off_until_a_skip() -> None:
    outcome = Task16Outcome()
    assert outcome.enabled is True
    assert outcome.jobs_skipped == 0
    assert outcome.skipped == []
