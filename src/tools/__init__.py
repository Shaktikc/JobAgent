"""Tools used by the agent graph nodes."""

from src.tools.answers import load_answers, normalize_question, save_answer
from src.tools.forms import (
    answers_match,
    looks_like_next,
    looks_like_resume_field,
    looks_like_submit,
    normalize_resume_name,
    pick_listed_resume,
    pick_next_button,
)
from src.tools.linkedin import (
    build_jobs_search_url,
    is_linkedin_url,
    is_logged_in_path,
    is_login_path,
    looks_like_apply_modal,
    looks_like_easy_apply,
    looks_like_easy_apply_action,
    looks_like_easy_apply_filter,
    looks_like_jobs_search_input,
    pick_easy_apply_action_index,
    pick_easy_apply_filter_index,
    pick_easy_apply_index,
)
from src.tools.matching import skills_in_text

# ``linkedin_best_matching_resume`` imports ``src.state``; importing it eagerly
# here makes ``src.state -> src.tools.self_healing.models`` circular (the graph
# state needs the Task 11 model). Re-export it lazily, exactly like
# :mod:`src.tools.browser` does for its moved modules.
_RESUME_REEXPORTS = frozenset({"RESUME_SUFFIXES", "extract_resume_text", "list_resume_files"})

__all__ = [
    "RESUME_SUFFIXES",
    "answers_match",
    "build_jobs_search_url",
    "extract_resume_text",
    "is_linkedin_url",
    "is_logged_in_path",
    "is_login_path",
    "list_resume_files",
    "load_answers",
    "looks_like_apply_modal",
    "looks_like_easy_apply",
    "looks_like_easy_apply_action",
    "looks_like_easy_apply_filter",
    "looks_like_jobs_search_input",
    "looks_like_next",
    "looks_like_resume_field",
    "looks_like_submit",
    "normalize_question",
    "normalize_resume_name",
    "pick_easy_apply_action_index",
    "pick_easy_apply_filter_index",
    "pick_easy_apply_index",
    "pick_listed_resume",
    "pick_next_button",
    "save_answer",
    "skills_in_text",
]


def __getattr__(name: str):
    """Import resume helpers on demand to keep the state/model import acyclic."""
    if name in _RESUME_REEXPORTS:
        import importlib

        resume_tools = importlib.import_module("src.tools.linkedin_best_matching_resume")
        return getattr(resume_tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
