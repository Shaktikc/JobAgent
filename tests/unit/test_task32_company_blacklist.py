"""Task 32: loading and matching the company blacklist (offline)."""

from __future__ import annotations

import json

import pytest

from src.tools import company_blacklist as cb


def _write(path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_parse_ignores_blank_names_and_normalizes() -> None:
    names = cb.parse_blacklist(["  Acme  ", "", "\tGlobex   Corp", "   "])
    assert names == frozenset({"acme", "globex corp"})


def test_parse_treats_a_single_string_as_one_name() -> None:
    assert cb.parse_blacklist("Acme") == frozenset({"acme"})


@pytest.mark.parametrize("company", ["Acme", " ACME ", "acme", "\tAcme\n"])
def test_whole_name_matches_ignoring_case_and_whitespace(company) -> None:
    assert cb.is_blacklisted(company, cb.parse_blacklist(["Acme"]))


@pytest.mark.parametrize("company", ["Acme Labs", "Acme, Inc.", "The Acme", "", None])
def test_similar_or_blank_names_do_not_match(company) -> None:
    assert not cb.is_blacklisted(company, cb.parse_blacklist(["Acme"]))


def test_repeated_inner_whitespace_matches() -> None:
    assert cb.is_blacklisted("Globex    Corp", cb.parse_blacklist(["globex corp"]))


def test_empty_list_matches_nothing() -> None:
    assert not cb.is_blacklisted("Acme", frozenset())
    assert cb.blacklisted_line("Engineer\nAcme", frozenset()) == ""


def test_blacklisted_line_compares_whole_lines() -> None:
    blacklist = cb.parse_blacklist(["Acme"])
    assert cb.blacklisted_line("Engineer\n ACME \nRemote", blacklist) == "ACME"
    assert cb.blacklisted_line("Engineer at Acme\nAcme Labs\nRemote", blacklist) == ""


def test_json_list_is_loaded(tmp_path) -> None:
    path = tmp_path / "companies.json"
    _write(path, ["Acme", " Globex  Corp ", ""])
    assert cb.load_blacklist(path) == frozenset({"acme", "globex corp"})


def test_missing_file_is_empty(tmp_path) -> None:
    assert cb.load_blacklist(tmp_path / "nope.json") == frozenset()


@pytest.mark.parametrize("text", ["", "  \n", "[]"])
def test_empty_file_or_list_is_empty(tmp_path, text) -> None:
    path = tmp_path / "companies.json"
    path.write_text(text, encoding="utf-8")
    assert cb.load_blacklist(path) == frozenset()


def test_file_with_bom_is_read(tmp_path) -> None:
    path = tmp_path / "companies.json"
    path.write_text('﻿["Acme", "Globex"]', encoding="utf-8")
    assert cb.load_blacklist(path) == frozenset({"acme", "globex"})


def test_unreadable_file_raises_a_clear_error(tmp_path) -> None:
    directory = tmp_path / "companies.json"
    directory.mkdir()  # exists, but reading it fails
    with pytest.raises(cb.BlacklistFileError, match="company blacklist"):
        cb.load_blacklist(directory)


@pytest.mark.parametrize(
    "text", ['["Acme",', '{"companies": ["Acme"]}', '"Acme"', '["Acme", 3]', "Acme"]
)
def test_invalid_json_or_shape_raises(tmp_path, text) -> None:
    path = tmp_path / "companies.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(cb.BlacklistFileError, match="company blacklist"):
        cb.load_blacklist(path)


def test_get_blacklist_loads_once_per_run(tmp_path, monkeypatch) -> None:
    path = tmp_path / "companies.json"
    _write(path, ["Acme"])
    monkeypatch.setattr(cb, "BLACKLIST_FILE", path)
    cb.reset_blacklist_cache()
    try:
        assert cb.get_blacklist() == frozenset({"acme"})
        _write(path, ["Globex"])
        assert cb.get_blacklist() == frozenset({"acme"})
        cb.reset_blacklist_cache()
        assert cb.get_blacklist() == frozenset({"globex"})
    finally:
        cb.reset_blacklist_cache()


def test_default_file_lives_at_the_project_root() -> None:
    assert cb.BLACKLIST_FILE.parent.name == "blacklist company"
    assert cb.BLACKLIST_FILE.name == "companies.json"
    # The user edits this file; it only has to be a valid list (or absent).
    assert isinstance(cb.load_blacklist(), frozenset)


def test_cli_stops_before_any_job_when_the_file_is_unreadable(
    tmp_path, monkeypatch, capsys
) -> None:
    from src import main as main_module

    path = tmp_path / "companies.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(cb, "BLACKLIST_FILE", path)
    cb.reset_blacklist_cache()

    def no_run(*_args, **_kwargs):
        raise AssertionError("the run must not start")

    monkeypatch.setattr(main_module, "_run", no_run)
    try:
        assert main_module.main(["--dry-run"]) == 2
    finally:
        cb.reset_blacklist_cache()
    assert "could not read the company blacklist" in capsys.readouterr().err
