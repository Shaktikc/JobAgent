"""Unit tests for the question → answer store."""

from __future__ import annotations

from src.tools.answers import load_answers, lookup_answer, normalize_question, save_answer


def test_normalize_question_trims_case_and_punctuation() -> None:
    assert normalize_question("  Phone   Number? ") == "phone number"
    assert normalize_question("Email address *") == "email address"
    assert normalize_question("Authorised to work?") == "authorised to work"
    assert normalize_question("") == ""


def test_load_answers_missing_file_is_empty(tmp_path) -> None:
    assert load_answers(tmp_path / "nope.json") == {}


def test_load_answers_normalizes_keys(tmp_path) -> None:
    path = tmp_path / "answers.json"
    path.write_text('{"  Email Address? ": "a@b.com"}', encoding="utf-8")
    assert load_answers(path) == {"email address": "a@b.com"}


def test_load_answers_ignores_bad_json(tmp_path) -> None:
    path = tmp_path / "answers.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_answers(path) == {}
    path.write_text('["a", "list"]', encoding="utf-8")
    assert load_answers(path) == {}


def test_save_answer_round_trips(tmp_path) -> None:
    path = tmp_path / "answers.json"
    key = save_answer(path, "Phone Number", "+61 400 000 000")
    assert key == "phone number"
    assert load_answers(path)["phone number"] == "+61 400 000 000"


def test_save_answer_updates_existing_mapping(tmp_path) -> None:
    path = tmp_path / "answers.json"
    save_answer(path, "City", "Sydney")
    save_answer(path, "city", "Melbourne")
    answers = load_answers(path)
    assert answers == {"city": "Melbourne"}


def test_lookup_answer_matches_any_candidate() -> None:
    answers = {"phone number": "+61", "city": "Sydney"}
    assert lookup_answer(answers, ["Phone Number"]) == ("phone number", "+61")
    assert lookup_answer(answers, ["nope", "City"]) == ("city", "Sydney")
    assert lookup_answer(answers, ["unknown"]) is None
    assert lookup_answer({}, ["anything"]) is None
