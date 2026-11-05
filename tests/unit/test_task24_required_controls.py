"""Missingness is evaluated across the question, never a single radio option."""

from src.tools.linkedin_validation.required_controls import group_for, held_answer, is_missing_issue


def test_checked_group_is_not_missing_because_other_options_are_empty():
    yes = {"kind": "radio", "name": "one", "question": "Tools*", "option": "Yes", "checked": True}
    no = dict(yes, option="No", checked=False)
    other = dict(no, question="Other*", name="other")
    assert group_for(no, [yes, no, other]) == [yes, no]
    assert held_answer([yes, no]) == "Yes"
    assert not is_missing_issue({"field": no, "message": "Invalid input"}, [yes, no, other])
    assert is_missing_issue({"field": no, "message": "This field is required"}, [yes, no])
