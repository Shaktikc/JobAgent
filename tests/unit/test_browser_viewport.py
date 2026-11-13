"""Headed sessions follow the real window; headless sessions retain fixed sizing."""

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import profiles


@pytest.mark.parametrize("headless", [False, True])
def test_viewport_mode_matches_visible_or_headless_browser(tmp_path, monkeypatch, headless):
    pytest.importorskip("browser_use")
    from browser_use import BrowserSession

    # Keep the real BrowserProfile validation: it can override no_viewport when
    # a non-null viewport is provided, so a kwargs-only mock misses the defect.
    monkeypatch.setattr(profiles, "_require_browser_use", lambda: BrowserSession)
    settings = Settings(data_dir=tmp_path, session=SessionSettings(
        headless=headless, viewport_width=1100, viewport_height=700,
    ))
    profile = profiles.build_browser(settings).browser_profile
    if headless:
        assert profile.viewport.width == 1100
        assert profile.viewport.height == 700
        assert profile.no_viewport is False
    else:
        assert profile.viewport is None
        assert profile.no_viewport is True
        assert profile.window_size.width == 1100
        assert profile.window_size.height == 700
