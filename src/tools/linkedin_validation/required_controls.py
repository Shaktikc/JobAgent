"""Identify one live question and verify that its real controls hold an answer."""

import re

from src.tools.browser import _marker_element
from src.tools.forms import answers_match


def group_for(field, fields):
    def matches(row):
        if row.get("question") != field.get("question") or row.get("kind") != field.get("kind"):
            return False
        return field.get("kind") == "checkbox" or row.get("name") == field.get("name")

    return [row for row in fields if matches(row)]


def held_answer(group):
    from src.tools.linkedin_easy_apply_fill.field_filling import _control_already_answered

    if not group:
        return None
    if group[0].get("kind") in {"radio", "checkbox"}:
        return ", ".join(row.get("option", "") for row in group if row.get("checked")) or None
    return str(group[0].get("value") or "") if _control_already_answered(group[0]) else None


def is_missing_issue(issue, fields):
    field = issue.get("field") or {}
    if not field:
        return False
    return bool(re.search(r"\brequired\b", issue.get("message", ""), re.I)) or not held_answer(
        group_for(field, fields)
    )


def unanswered_issues(fields):
    from src.tools.linkedin_easy_apply_fill.required_only import is_required_field

    return [
        {
            "question": field["question"],
            "message": "Required question is unanswered",
            "field": field,
        }
        for field in fields
        if is_required_field(field) and not held_answer(group_for(field, fields))
    ]


def usable_answer(group, answer):
    from src.tools.linkedin_easy_apply_fill.checkbox_groups import selected_options
    from src.tools.linkedin_easy_apply_fill.field_filling import _select_value_for

    if not group or answer is None or not str(answer).strip():
        return False
    kind = group[0].get("kind")
    if kind == "radio":
        return any(answers_match(row.get("option", ""), answer) for row in group)
    if kind == "checkbox":
        return bool(selected_options(answer, [row.get("option", "") for row in group]))
    if kind == "select":
        return _select_value_for(answer, group[0].get("options") or []) is not None
    return True


async def apply_answer(page, field, answer, read):
    """Re-enumerate after every action and verify the entire expected selection."""
    from src.tools.linkedin_easy_apply_fill.checkbox_groups import selected_options
    from src.tools.linkedin_easy_apply_fill.field_filling import _fill_field, _select_value_for

    snapshot = await read(page)
    group = group_for(field, snapshot[2])
    if not usable_answer(group, answer):
        return False
    kind = field.get("kind")
    if kind in {"radio", "checkbox"}:
        options = [row.get("option", "") for row in group]
        wanted = (
            [next(opt for opt in options if answers_match(opt, answer))]
            if kind == "radio"
            else selected_options(answer, options)
        )
        for option in wanted:
            group = group_for(field, (await read(page))[2])
            row = next((f for f in group if f.get("option") == option), None)
            if row is None:
                return False
            if row.get("checked"):
                continue
            element = await _marker_element(page, "data-autojob-fill", row["marker"])
            if element is None or not (await _fill_field(element, row, option))[0]:
                return False
        actual = [
            f.get("option") for f in group_for(field, (await read(page))[2]) if f.get("checked")
        ]
        return set(actual) == set(wanted)
    row = group[0]
    expected = (
        _select_value_for(answer, row.get("options") or []) if kind == "select" else str(answer)
    )
    if str(row.get("value") or "") != expected:
        element = await _marker_element(page, "data-autojob-fill", row["marker"])
        if element is None or not (await _fill_field(element, row, expected))[0]:
            return False
    fresh = group_for(field, (await read(page))[2])
    return bool(fresh and str(fresh[0].get("value") or "").strip() == expected.strip())
