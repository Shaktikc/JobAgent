"""Panel text is readable and credential shapes never reach the DOM."""

import pytest

from src.tools.linkedin_status_overlay.panel_text import sanitize_panel_text


def test_whitespace_and_length():
    assert sanitize_panel_text("  first\n\t second  \r\nthird ") == "first second third"
    result = sanitize_panel_text("word " * 100)
    assert len(result) == 280
    assert result.endswith("…")


@pytest.mark.parametrize("secret", [
    "sk-proj-abcdefghijklmnop123456", "Bearer abc.def-123_xyz",
    "abcdef0123456789" * 4, "AbCdEfGh0123456789+/" * 4,
    "api_key=short-secret", 'password="two words"',
])
def test_credentials_are_redacted_before_truncating(secret):
    result = sanitize_panel_text("Opening job " + secret + " now")
    assert secret not in result
    assert "[redacted]" in result


def test_normal_activity_is_preserved():
    message = "Task 2: job 10 is already applied; skipping."
    assert sanitize_panel_text(message) == message
