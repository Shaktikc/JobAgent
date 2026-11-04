"""Lazy compatibility exports for the task-specific browser flows."""

# Task 1's LinkedIn job-search flow (login, search, the optional "Try AI job
# search" detour, and the Easy Apply filter) now lives in
# :mod:`src.tools.linkedin_search`. The names are re-exported lazily so existing
# callers and tests can keep importing them from this module. The re-export must
# be lazy: linkedin_search imports this module's shared primitives at load time,
# so importing it here at load time would create a cycle.
_TASK1_REEXPORTS = frozenset(
    {
        "_AI_CANDIDATES_QUERY",
        "_EASY_APPLY_FILTER_SELECTORS",
        "_FILTER_QUERY",
        "_JOBS_SEARCH_INPUT_SELECTORS",
        "_JOBS_SEARCH_SUBMIT_SELECTORS",
        "_JOBS_TAB_URL",
        "_LOGIN_STATE_QUERY",
        "_MAX_AI_JOB_SEARCH_CLICKS",
        "_task1_ok",
        "_task1_on_page",
        "click_ai_job_search",
        "easy_apply_filter_selected",
        "find_ai_job_search_button",
        "find_easy_apply_filter",
        "find_jobs_search_input",
        "is_logged_in",
        "open_jobs_search",
        "read_ai_job_search_candidates",
        "run_ai_job_search_detour",
        "run_task1",
        "select_easy_apply_filter",
        "type_jobs_search",
        "wait_for_ai_job_search_button",
        "wait_for_login",
    }
)

# Task 2's job-selection flow (read the job list, pick a job, click its Easy Apply
# button, and confirm the form opened) now lives in
# :mod:`src.tools.linkedin_job_selection`. Re-exported lazily for the same reason
# as Task 1: linkedin_job_selection imports this module's shared primitives at
# load time, so importing it here at load time would create a cycle.
_TASK2_REEXPORTS = frozenset(
    {
        "_APPLY_MODAL_QUERY",
        "_JOB_CARD_SELECTORS",
        "_JOB_DETAILS_APPLY_SELECTORS",
        "_element_is_job_card",
        "_first_line",
        "_task2_ok",
        "_task2_on_page",
        "_task2_selected_ok",
        "find_job_apply_button",
        "read_apply_modal",
        "read_job_cards",
        "wait_for_easy_apply_modal",
        "wait_for_job_apply_button",
    }
)

# Task 3's flow (read the open job's description and pick the best-matching
# resume) now lives in :mod:`src.tools.linkedin_best_matching_resume`. Re-exported
# lazily for the same reason as Tasks 1-2: that module imports this module's
# shared primitives at load time, so importing it here would create a cycle.
_TASK3_REEXPORTS = frozenset(
    {
        "_JOB_DESCRIPTION_QUERY",
        "read_job_description",
    }
)

# Task 4's fill flow (enumerate the Easy Apply form, fill known fields, attach the
# resume, and advance steps without submitting) now lives in
# :mod:`src.tools.linkedin_easy_apply_fill`. Re-exported lazily for the same
# reason as Tasks 1-3: that module (via :mod:`src.tools.linkedin_ask_human`)
# imports this module's shared primitives at load time, so importing it here at
# load time would create a cycle.
_TASK4_REEXPORTS = frozenset(
    {
        "_ENUMERATE_FORM_QUERY",
        "_FILL_INPUT_JS",
        "_FILL_SELECT_JS",
        "_FORM_BUTTONS_QUERY",
        "_MAX_FORM_STEPS",
        "_RESUME_OPTIONS_QUERY",
        "_SELECT_PLACEHOLDERS",
        "_attach_resume",
        "_blocked_note",
        "_blocking_questions",
        "_choice_hint",
        "_control_already_answered",
        "_fill_field",
        "_fill_step",
        "_form_signature",
        "_resume_file_selector",
        "_resume_listed_names",
        "_select_value_for",
        "_task4_ok",
        "_task4_on_page",
        "enumerate_form_fields",
        "read_form",
        "read_form_buttons",
        "read_resume_info",
        "read_resume_options",
        "upload_file_via_cdp",
    }
)

# Task 5's ask-the-human flow (show a browser banner for an unknown question,
# read the answer the human types into the form, and remember it) now lives in
# :mod:`src.tools.linkedin_ask_human`. Re-exported lazily for the same reason as
# Tasks 1-4: that module imports this module's shared primitives at load time, so
# importing it here at load time would create a cycle.
_TASK5_REEXPORTS = frozenset(
    {
        "_HIDE_UNKNOWN_JS",
        "_READ_FORM_ANSWER_JS",
        "_READ_UNKNOWN_JS",
        "_SHOW_UNKNOWN_JS",
        "_WATCH_FORM_ANSWER_JS",
        "_remember_answer",
        "ask_human_for_answer",
    }
)


def __getattr__(name: str):
    """Re-export the moved Task 1-5 names from their modules."""
    if name in _TASK1_REEXPORTS:
        from src.tools import linkedin_search

        return getattr(linkedin_search, name)
    if name in _TASK2_REEXPORTS:
        from src.tools import linkedin_job_selection

        return getattr(linkedin_job_selection, name)
    if name in _TASK3_REEXPORTS:
        from src.tools import linkedin_best_matching_resume

        return getattr(linkedin_best_matching_resume, name)
    if name in _TASK4_REEXPORTS:
        from src.tools import linkedin_easy_apply_fill

        return getattr(linkedin_easy_apply_fill, name)
    if name in _TASK5_REEXPORTS:
        from src.tools import linkedin_ask_human

        return getattr(linkedin_ask_human, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
