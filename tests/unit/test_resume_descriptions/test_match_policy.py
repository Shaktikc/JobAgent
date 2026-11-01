"""Task 16: accept rated partial/strong candidates without trusting conflicting fit."""

from __future__ import annotations

import json

import pytest

from src.state import JobDescription
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    parse_match,
    pick_best_resume,
)

from .helpers import FakeClient, make_settings


@pytest.mark.parametrize(
    ("choice", "fit", "ratings", "selected", "resolved_fit"),
    [
        ("c1", "partial", {"c1": "partial"}, "a.pdf", "partial"),
        ("c1", "strong", {"c1": "partial", "c2": "strong"}, "b.pdf", "strong"),
        ("c1", "partial", {"c1": "strong"}, "a.pdf", "strong"),
        ("none", "none", {"c2": "partial"}, "b.pdf", "partial"),
        ("c2", "partial", {"c1": "partial", "c2": "partial"}, "b.pdf", "partial"),
        ("c1", "strong", {"c1": "none"}, None, "none"),
        ("c1", "strong", {}, None, ""),
        ("c1", "partial", {"c9": "strong"}, None, ""),
    ],
)
def test_candidate_ratings_decide_eligibility(choice, fit, ratings, selected, resolved_fit):
    match = parse_match(
        json.dumps({"choice": choice, "fit": fit, "ratings": ratings}),
        {"c1": "a.pdf", "c2": "b.pdf"},
    )

    assert match.selected_path == selected
    assert match.fit == resolved_fit
    assert match.is_eligible is (selected is not None)


def test_conflicting_top_level_fit_is_recorded_without_promoting_the_resume():
    match = parse_match(
        '{"choice":"c1","fit":"strong","ratings":{"c1":"partial"}}',
        {"c1": "a.pdf"},
    )

    assert match.fit == "partial"
    assert match.is_eligible
    assert not match.is_strong
    assert "partial" in match.rationale and "strong" in match.rationale


@pytest.mark.parametrize("reply", ["{}", '{"error":"upstream unavailable"}', '{"fit":"strong"}'])
def test_json_without_a_match_decision_raises(reply):
    with pytest.raises(ResumeDescriptionError, match="unusable match reply"):
        parse_match(reply, {"c1": "a.pdf"})


async def test_unusable_json_uses_the_existing_retry_before_accepting_a_partial(tmp_path):
    client = FakeClient([
        '{"error":"upstream unavailable"}',
        '{"choice":"c1","fit":"partial","ratings":{"c1":"partial"}}',
    ])
    result = await pick_best_resume(
        JobDescription(title="Cloud Engineer", body="AWS Terraform"),
        [("a.pdf", ResumeDescription(summary="Cloud engineer"))],
        make_settings(tmp_path, api_key="test", model="test"),
        client=client,
    )

    assert len(client.calls) == 2
    assert result.selected_path == "a.pdf" and result.fit == "partial"
