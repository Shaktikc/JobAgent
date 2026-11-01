"""Task 16 routes partial and strong matches to Easy Apply, with no fallback."""

from __future__ import annotations

import importlib
import json

import pytest

from src.configuration import SessionSettings, Settings
from src.graph import _route_after_match
from src.state import JobDescription, Task2Outcome, new_state
from src.tools.linkedin_best_matching_resume import selection
from src.tools.resume_descriptions import ResumeDescription, parse_match

match_node = importlib.import_module("src.nodes.match")


@pytest.mark.parametrize("fit", ["partial", "strong", "none", ""])
async def test_match_routes_by_the_candidate_rating(tmp_path, monkeypatch, fit):
    pool = tmp_path / "resumes"
    pool.mkdir()
    resume = pool / "engineer.txt"
    resume.write_text("Python cloud engineer", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", resumes_dir=pool)

    async def describe(path, configured):
        return ResumeDescription(summary="Python cloud engineer")

    async def pick(job, candidates, configured):
        return parse_match(
            json.dumps({"choice": "c1", "fit": fit, "ratings": {"c1": fit}}),
            {"c1": candidates[0][0]},
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("strict mode must not consult a fallback or ask for a resume")

    monkeypatch.setattr(match_node, "load_settings", lambda: settings)
    monkeypatch.setattr(selection, "describe_resume", describe)
    monkeypatch.setattr(selection, "pick_best_resume", pick)
    monkeypatch.setattr(selection, "load_library", forbidden)
    monkeypatch.setattr(selection, "ask_human_for_resume", forbidden)
    monkeypatch.setattr(selection, "store_uploaded_resume", forbidden)
    state = new_state(dry_run=False, resumes_dir=str(pool))
    state.update(
        task2=Task2Outcome(job_index=0, job_title="Cloud Engineer", job_selected=True),
        job_description=JobDescription(title="Cloud Engineer", body="Build cloud services."),
    )

    result = await match_node.match(state)

    assert not result.get("errors")
    assert result["task3"].asked_human is False
    assert result["task3"].reused_from_library == ""
    if fit in {"partial", "strong"}:
        assert result["task3"].selected_path == str(resume)
        assert result["task3"].fit == fit
        assert result["task3"].no_match is False
        assert _route_after_match(result) == "open_form"
        assert "task16" not in result and "skipped_titles" not in result
    else:
        assert result["task3"].selected_path is None
        assert result["task3"].no_match is True
        assert _route_after_match(result) == "next_job"
        assert result["task16"].jobs_skipped == 1
        assert result["skipped_titles"] == ["cloud engineer"]


async def test_legacy_mode_keeps_a_rated_partial_instead_of_requesting_a_resume(tmp_path):
    resume = tmp_path / "engineer.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data", resumes_dir=tmp_path,
        session=SessionSettings(require_resume_match=False),
    )

    async def describe(path):
        return ResumeDescription(summary="Python engineer")

    async def pick(job, candidates):
        return parse_match(
            '{"choice":"c1","ratings":{"c1":"partial"}}', {"c1": str(resume)}
        )

    result = await selection.ensure_resume(
        JobDescription(title="Cloud Engineer", body="Python AWS"), tmp_path, settings,
        describer=describe, matcher=pick,
    )

    assert result.selected_path == str(resume) and result.fit == "partial"
    assert not result.asked_human and not result.reused_from_library
