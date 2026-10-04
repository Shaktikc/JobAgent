"""Unit tests for the pure Easy Apply form helpers."""

from __future__ import annotations

from src.tools.forms import (
    answers_match,
    looks_like_next,
    looks_like_resume_field,
    looks_like_submit,
    normalize_resume_name,
    pick_listed_resume,
    pick_next_button,
)


def test_normalize_resume_name() -> None:
    assert (
        normalize_resume_name("ShaktiKC_Resume_python_Node_Senior.pdf")
        == "shaktikcresumepythonnodesenior"
    )
    assert normalize_resume_name("/a/b/CV Python.pdf") == "cvpython"
    assert normalize_resume_name("") == ""


def test_pick_listed_resume_exact_and_extension_insensitive() -> None:
    listed = ["ShaktiKC_Resume_python_Node_Senior.pdf", "Other.docx"]
    assert (
        pick_listed_resume("ShaktiKC_Resume_python_Node_Senior.pdf", listed)
        == "ShaktiKC_Resume_python_Node_Senior.pdf"
    )
    assert (
        pick_listed_resume("ShaktiKC_Resume_python_Node_Senior", listed)
        == "ShaktiKC_Resume_python_Node_Senior.pdf"
    )


def test_pick_listed_resume_tolerates_label_suffix() -> None:
    listed = ["ShaktiKC_Resume_python_Node_Senior.pdf Selected"]
    assert pick_listed_resume("ShaktiKC_Resume_python_Node_Senior.pdf", listed) == listed[0]


def test_pick_listed_resume_no_match() -> None:
    assert pick_listed_resume("python.pdf", ["java.docx"]) is None
    assert pick_listed_resume("", ["a.pdf"]) is None
    assert pick_listed_resume("a.pdf", []) is None


def test_looks_like_submit_and_next() -> None:
    assert looks_like_submit("Submit application")
    assert looks_like_submit("Submit your application")
    assert not looks_like_next("Submit application")
    assert looks_like_next("Next")
    assert looks_like_next("Continue")
    assert looks_like_next("Review your application")
    assert not looks_like_next("Save")


def test_pick_next_button_skips_submit_and_disabled_buttons() -> None:
    buttons = [
        {"marker": "b0", "text": "Submit application", "disabled": False},
        {"marker": "b1", "text": "Next", "disabled": False},
    ]
    assert pick_next_button(buttons)["marker"] == "b1"
    assert pick_next_button([{"marker": "b0", "text": "Submit application"}]) is None
    assert pick_next_button([{"marker": "b1", "text": "Next", "disabled": True}]) is None


def test_answers_match() -> None:
    assert answers_match("Yes", "yes")
    assert answers_match("Yes, I am authorised", "Yes")
    assert answers_match("5 years", "5")
    assert not answers_match("No", "Yes")
    assert not answers_match("", "Yes")
    assert not answers_match("Yes", "")


def test_looks_like_resume_field() -> None:
    assert looks_like_resume_field("Resume", ["ShaktiKC_Resume.pdf"])
    assert looks_like_resume_field("Upload your resume", [])
    assert looks_like_resume_field("Choose document", ["cv.pdf", "other.docx"])
    assert not looks_like_resume_field("Are you authorised to work?", ["Yes", "No"])
