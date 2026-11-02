"""Posting identity uses direct links and IDs, including LinkedIn semantic cards."""

import pytest

from src.tools.linkedin_validation.identity import job_id_from_url, read_card_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/jobs/view/123/?tracking=abc", "123"),
        ("https://www.linkedin.com/jobs/search/?currentJobId=456", "456"),
        ("https://www.linkedin.com/jobs/search/?jobId=789", "789"),
        ("https://evil.example/jobs/view/123/", ""),
        ("https://linkedin.com.evil.example/jobs/view/123/", ""),
        ("https://www.linkedin.com/jobs/search/", ""),
    ],
)
def test_extract_only_linkedin_posting_ids(url, expected):
    assert job_id_from_url(url) == expected


async def test_semantic_card_id_is_read_from_componentkey():
    class Card:
        async def evaluate(self, script):
            assert "componentkey" in script
            return "123"

    assert await read_card_id(Card()) == "123"
