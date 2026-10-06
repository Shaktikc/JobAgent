# Done Tasks

Completed-work log for this project. When a task in `task.md` is finished:

1. Mark it ✅ Done in `task.md`.
2. Add an entry below with the task number, title, date, and the evidence that
   proves it is done (tests, run output, screenshots, or code references).

Keep newest work at the bottom so the log reads chronologically.

| # | Task | Status | Completed |
| - | ---- | ------ | --------- |
| 1 | Log in to LinkedIn, search "software engineer", select Easy Apply | ✅ Done | 2026-10-04 |
| 2 | Select Easy Apply from the job list | ✅ Done | 2026-10-04 |
| 3 | Read the job description and pick the best-matching resume | ✅ Done | 2026-10-04 |
| 4 | Open Easy Apply and start filling the application form | ✅ Done | 2026-10-04 |
| 5 | Ask the human for unknown answers, remember them, and show UI feedback | ✅ Done | 2026-10-04 |

---

## Task 4 — Open Easy Apply and start filling the application form

**Status:** ✅ Done
**Completed:** 2026-10-06

**What was done (update: fixed the form not auto-filling)**

The Easy Apply form opened but its known fields were not auto-filled from the
answer store. Root cause: Task 4's field-enumeration JS (`_ENUMERATE_FORM_QUERY`
and the resume-options query) only recognized LinkedIn's older form markup
(`.fb-dash-form-element`, `.jobs-easy-apply-form-element`, `label[for=id]`). On
LinkedIn's newer Easy Apply markup the screening questions render as styled
`[role="radio"]` divs inside `.jobs-easy-apply-form-section__grouping` with the
question text in a `.fb-form-element-label`. Those questions were enumerated with
bare markers (`f1`, `f2`) instead of their real text, so no stored answer ever
matched and nothing was filled.

Fix (in `src/tools/browser.py`):
- `ownLabel` / `groupLabel` now also recognize the newer containers
  (`.jobs-easy-apply-form-section__grouping`, `.jobs-easy-apply-form-section`,
  `.fb-form-element-wrapper`, `.fb-form-element`) and the `.fb-form-element-label`
  question element.
- A `[role="radio"]` / `[role="checkbox"]` div reports its own visible text as the
  option label (e.g. "Yes"/"No"), so a stored answer can be matched to the right
  option.
- The same label-extraction improvements were applied to the resume-options query
  so resume radio lists in the new markup are still detected.

**Evidence**
- Reproduced against a realistic 2026 LinkedIn-shaped fixture: before the fix the
  screening question enumerated as `question='f1'` and `known_fields` was 1 (only
  the phone field); after the fix `known_fields` is 2 and the stored "Yes" answer
  is applied to the radio group.
- New live-browser regression test:
  `tests/integration/test_fill_form_live.py::test_task4_autofills_screening_questions_in_new_linkedin_markup`
  (drives the real `_task4_on_page` over the new markup and asserts the screening
  question auto-fills, the listed resume is selected, and Submit is never clicked).
- `uv run pytest` → all pass (live tests skipped by default);
  `AUTOJOB_FILL_LIVE=1 uv run pytest tests/integration/test_fill_form_live.py` →
  4 passed.
