"""Unit tests for `filling` (Task 7): selectors and single-step fill decisions.

No browser: a saved Easy Apply modal fixture is parsed with the stdlib, and the
module-level selectors in ``nodes/fill.py`` must resolve the expected nodes
(SPEC.md §6, "selector tests"). The pure widget classifier and screenshot naming
are tested here too. The live fill path is exercised by the T8 ``run --url`` smoke.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.nodes import fill
from src.nodes.fill import (
    Disposition,
    Widget,
    WidgetKind,
    artifact_path,
    decide,
    lookup_answer,
    normalize_label,
    widget_kind,
)
from src.tools.store import Answer, Provenance

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
MODAL_HTML = (FIXTURES / "easy_apply_modal.html").read_text(encoding="utf-8")
# The live 2026 "Aero" modal: a native <dialog data-testid="dialog">, not a
# div[role="dialog"]. Captured on 2026-09-30 (see the fixture's comment).
AERO_MODAL_HTML = (FIXTURES / "easy_apply_modal_aero.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A minimal CSS-selector evaluator (tag/[attr]/[attr="v"]/.class/#id, comma OR).
# Enough for the flat selector constants this module uses; the real page is
# driven by Playwright, which has a full engine.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _El:
    tag: str
    attrs: dict[str, str | None]


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[_El] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def _add(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append(_El(tag.lower(), {name: value for name, value in attrs}))


_PART_RE = re.compile(
    r'\[(?P<attr>[\w:-]+)(?:=(?P<q>["\'])(?P<val>.*?)(?P=q))?\]'
    r'|\.(?P<cls>[\w-]+)'
    r'|#(?P<id>[\w-]+)'
)


def _matches_term(element: _El, term: str) -> bool:
    tag_match = re.match(r"^(?P<tag>[A-Za-z][\w-]*)", term)
    tag = tag_match.group("tag") if tag_match else None
    rest = term[len(tag) :] if tag else term
    if tag and element.tag != tag.lower():
        return False
    for part in _PART_RE.finditer(rest):
        if part.group("attr") is not None:
            attr = part.group("attr")
            if attr not in element.attrs:
                return False
            expected = part.group("val")
            if expected is not None and (element.attrs[attr] or "") != expected:
                return False
        elif part.group("cls") is not None:
            if part.group("cls") not in (element.attrs.get("class") or "").split():
                return False
        elif part.group("id") is not None:
            if (element.attrs.get("id") or "") != part.group("id"):
                return False
    return True


def query(html: str, selector: str) -> list[_El]:
    collector = _Collector()
    collector.feed(html)
    collector.close()
    terms = [t.strip() for t in selector.split(",") if t.strip()]
    return [el for el in collector.elements if any(_matches_term(el, t) for t in terms)]


# --- matcher sanity (so selector assertions mean something) -----------------


def test_matcher_matches_tag_and_attribute_value() -> None:
    assert len(query(MODAL_HTML, 'input[type="text"]')) == 2


def test_matcher_supports_comma_or() -> None:
    assert len(query(MODAL_HTML, "select, textarea")) == 1


# --- selectors resolve the fixture ------------------------------------------


def test_easy_apply_button_selector_resolves_the_apply_button() -> None:
    found = query(MODAL_HTML, fill.EASY_APPLY_BUTTON_SELECTOR)

    assert len(found) == 1
    assert found[0].tag == "button"
    assert found[0].attrs.get("data-view-name") == "job-apply-button"


def test_modal_selector_resolves_the_dialog() -> None:
    found = query(MODAL_HTML, fill.MODAL_SELECTOR)

    assert len(found) == 1
    assert found[0].attrs.get("role") == "dialog"


def test_modal_selector_resolves_the_aero_dialog() -> None:
    """The live 2026 modal is a native <dialog data-testid="dialog">.

    Regression: the previous selector only matched div[role="dialog"], so the real
    Easy Apply form never resolved and the run died opening the modal.
    """
    found = query(AERO_MODAL_HTML, fill.MODAL_SELECTOR)

    assert len(found) == 1
    assert found[0].tag == "dialog"
    assert found[0].attrs.get("data-testid") == "dialog"


def test_step_control_selector_sees_aero_contact_controls() -> None:
    found = query(AERO_MODAL_HTML, fill.STEP_CONTROL_SELECTOR)

    assert {el.attrs.get("id") for el in found} == {"email", "country", "phone"}


def test_text_input_selector_resolves_only_text_fields() -> None:
    found = query(MODAL_HTML, fill.TEXT_INPUT_SELECTOR)

    assert {el.attrs.get("id") for el in found} == {"city", "salary"}


def test_text_input_selector_does_not_match_select_or_radios() -> None:
    found = query(MODAL_HTML, fill.TEXT_INPUT_SELECTOR)

    assert all(el.tag == "input" and el.attrs.get("type") == "text" for el in found)


def test_file_input_selector_resolves_the_resume_input() -> None:
    found = query(MODAL_HTML, fill.FILE_INPUT_SELECTOR)

    assert len(found) == 1
    assert found[0].attrs.get("id") == "resume"


def test_step_control_selector_sees_every_control() -> None:
    found = query(MODAL_HTML, fill.STEP_CONTROL_SELECTOR)

    # city, salary, sponsor(select), 2 radios, resume(file)
    assert len(found) == 6


# --- widget classification --------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "input_type", "expected"),
    [
        ("input", "text", WidgetKind.TEXT),
        ("input", None, WidgetKind.TEXT),
        ("input", "number", WidgetKind.TEXT),
        ("input", "email", WidgetKind.TEXT),
        ("textarea", None, WidgetKind.TEXT),
        ("input", "file", WidgetKind.FILE),
        ("input", "radio", WidgetKind.RADIO),
        ("input", "checkbox", WidgetKind.CHECKBOX),
        ("select", None, WidgetKind.SELECT),
        ("input", "date", WidgetKind.UNKNOWN),
        ("button", None, WidgetKind.UNKNOWN),
    ],
)
def test_widget_kind_classification(
    tag: str, input_type: str | None, expected: WidgetKind
) -> None:
    assert widget_kind(tag, input_type) is expected


# --- label normalisation and lookup -----------------------------------------


def test_normalize_label_strips_required_star_and_spacing() -> None:
    assert normalize_label("  What is your   expected salary? * ") == (
        "what is your expected salary?"
    )


def test_lookup_answer_is_case_and_whitespace_insensitive() -> None:
    answers = {"City": Answer("City", "Boston", Provenance.RESUME, 1.0)}

    assert lookup_answer(answers, "  city ") == answers["City"]


def test_lookup_answer_returns_none_when_absent() -> None:
    assert lookup_answer({}, "City") is None


# --- fill decisions ---------------------------------------------------------


def _answer(value: str, provenance: Provenance = Provenance.FACTS_RULE) -> Answer:
    return Answer("q", value, provenance, 1.0)


def test_decide_fills_a_text_widget_that_has_an_answer() -> None:
    widget = Widget(label="City", kind=WidgetKind.TEXT, required=True)
    answers = {"City": _answer("Boston")}

    decision = decide(widget, answers)

    assert decision.disposition is Disposition.FILL
    assert decision.answer is not None
    assert decision.answer.value == "Boston"


def test_decide_flags_a_text_widget_with_no_answer() -> None:
    decision = decide(Widget(label="Favorite color", kind=WidgetKind.TEXT), {})

    assert decision.disposition is Disposition.FLAG
    assert decision.answer is None


def test_decide_never_fills_an_empty_or_needs_review_answer() -> None:
    widget = Widget(label="City", kind=WidgetKind.TEXT)
    empty = {"City": Answer("City", "", Provenance.NEEDS_REVIEW, 0.0)}

    assert decide(widget, empty).disposition is Disposition.FLAG


def test_decide_treats_a_file_widget_as_upload() -> None:
    decision = decide(Widget(label="Resume", kind=WidgetKind.FILE), {})

    assert decision.disposition is Disposition.UPLOAD


@pytest.mark.parametrize("kind", [WidgetKind.SELECT, WidgetKind.RADIO, WidgetKind.CHECKBOX])
def test_decide_flags_unrecognised_widgets_without_guessing(kind: WidgetKind) -> None:
    """Task 14 handles these; Task 7 must leave them blank and surface them."""
    decision = decide(Widget(label="Do you require sponsorship?", kind=kind, required=True), {})

    assert decision.disposition is Disposition.FLAG
    assert decision.answer is None


# --- screenshots ------------------------------------------------------------


def test_artifact_path_is_a_png_under_the_artifacts_dir(tmp_path: Path) -> None:
    path = artifact_path(tmp_path, "4012345678")

    assert path.parent == tmp_path
    assert path.name.startswith("4012345678-")
    assert path.suffix == ".png"


def test_artifact_path_sanitises_the_job_id(tmp_path: Path) -> None:
    path = artifact_path(tmp_path, "4123/../bad id")

    assert "/" not in path.name
    assert " " not in path.name
    assert path.name.endswith(".png")
