# Task 4 — Bugs (fill the Easy Apply form)

Bugs whose root cause is in **Task 4**: enumerating the Easy Apply form, filling
known controls, attaching the resume, and advancing the steps.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-002 | unreadable form silently looked empty → every field `NEEDS_REVIEW` | 🟢 Fixed | `24d381f` |
| BUG-003 | fill only touched the first modal step (`1/4` pages) | 🟢 Fixed | `24d381f` |
| BUG-005 | no screenshot on a failed application | 🟢 Fixed | `14719e9` |
| BUG-022 | inline hashed-class Easy Apply form not found | 🟢 Fixed | `84b0bb5` |
| BUG-023 | first matching modal was a hidden unrelated dialog | 🟢 Fixed | (Task 4 modal fix) |
| BUG-032 | walk stopped at a field-less review step ("form did not advance") | 🟢 Fixed | (uncommitted) |

---

### BUG-002 — an unreadable form silently looked empty

- **Symptom:** when the agent produced no `FormField`s, `open_and_read_fields`
  returned `()`, every answer became `NEEDS_REVIEW`, and the job looked like an
  empty form.
- **Root cause:** a broken read was indistinguishable from an empty form.
- **Fix:** raise `FillError`; `_node_answer` persists `JobStatus.FAILED` before
  propagating, mirroring `_node_fill`.
- **Evidence:** `tests/unit/test_fill_read_fields.py` (8),
  `tests/unit/test_browser_agent_tasks.py`. Commit `24d381f`.

### BUG-003 — the fill only touched the first modal step

- **Symptom:** the live Easy Apply form was `1/4 pages`; only step 1 was filled.
- **Root cause:** `READ_FORM_TASK` and the fill task never advanced the modal.
- **Fix:** both advance with **Next/Continue** through every step and still never
  submit.
- **Evidence:** `tests/unit/test_fill_read_fields.py`. Commit `24d381f`.

### BUG-005 — no screenshot on a failed application

- **Symptom:** the requirement "a PNG for every application" was violated on
  failure — screenshots were captured only on success.
- **Root cause:** `fill_application` captured only the success path.
- **Fix:** capture the failing form (`tag='failure'`) before re-raising; a
  screenshot error is logged without masking the original failure.
- **Evidence:** `tests/unit/test_fill_agent.py`. Commit `14719e9`.

### BUG-022 — the inline hashed-class Easy Apply form was not found

- **Symptom:** on the AI/semantic job view the inline full-page application form
  was not recognised, so nothing was filled.
- **Root cause:** LinkedIn has two layouts — the classic artdeco modal and an
  inline form whose classes are hashed. The queries only matched the classic
  modal.
- **Fix:** `FIND_APPLY_ROOT_JS` defines `findApplyRoot()`, used by the enumerate /
  resume-options / buttons queries, to find either layout (classic dialog, or an
  inline form anchored on a phone/email control or "Apply to <company>" heading).
  `_with_apply_root` injects it into the self-contained Task 4 queries.
- **Evidence:** `src/tools/browser.py`, `src/tools/linkedin_easy_apply_fill.py`,
  `src/tools/linkedin_job_selection.py`;
  `test_task4_fills_inline_hashed_class_form`. Commit `84b0bb5`.

### BUG-023 — the first matching modal was a hidden unrelated dialog

- **Symptom:** the fill walk enumerated zero fields and filled nothing.
- **Root cause:** an unrelated hidden `.artdeco-modal` (e.g. "Save this job")
  appeared before the Easy Apply modal, and the lookup used the *first* match.
- **Fix:** prefer the Easy Apply dialog, then the first **visible** dialog holding
  form controls or "Easy Apply" text.
- **Evidence:** `src/tools/browser.py` (`FIND_APPLY_ROOT_JS`);
  `test_task4_ignores_a_hidden_dialog_before_the_easy_apply_modal`.

### BUG-032 — the walk stopped at a field-less review step ("form did not advance")

- **Symptom:** on a multi-step Easy Apply form the walk stopped at a profile
  **review/edit** step (e.g. "Work experience", shown as `3/7 pages`) with the
  note `form did not advance to a new step`, even though Next was enabled and more
  steps remained. Log tail: `fill: no resume control found on this form step;
  form did not advance to a new step; stopping before Submit`.
- **Root cause:** `_form_signature` fingerprinted a step from
  `modal.querySelector('h3')` plus the enumerated fields. On LinkedIn the first
  `<h3>` is the modal title (`Apply to <company>`, constant), and review/edit steps
  hold **no fillable controls**, so two consecutive review steps produced an
  identical fingerprint. The walk wrongly concluded Next had not advanced and
  stopped before the terminal step.
- **Fix:** `_ENUMERATE_FORM_QUERY` now also returns a `step` identity and
  `_form_signature` includes it, so field-less steps are told apart. The identity
  is the modal's progress indicator ("3/7 pages"), its headings, **and a hash of
  the modal's whole visible text**. The first attempt (progress + headings only,
  commit `97c157d`) was insufficient on the live page: the progress/step-heading
  signal did not change between the review steps, so the walk still stopped. The
  whole-text hash always changes with the step's rendered content. (Also split
  `form_queries.py` into the `form_queries/` package — `scripts.py` + `readers.py`
  — per the file-size rule.)
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py`
  (`_ENUMERATE_FORM_QUERY` step identity: progress + headings + visible-text hash),
  `src/tools/linkedin_easy_apply_fill/form_queries/readers.py` (`read_form`),
  `src/tools/linkedin_easy_apply_fill/form_walk.py` (`_form_signature`,
  `_task4_on_page`, which logs `Task 4: step N: ... step_id=...`);
  `tests/unit/test_task4_review_steps.py` (2 tests; both fail without the fix);
  live-browser reproduction with the progress indicator placed *outside* the modal
  and the step titles as plain `<div>`s (so only the text hash distinguishes the
  steps): `step_id` `text:1029807389` → `text:3706210911` → `text:2325457445`,
  `steps_advanced` 2, `reached_terminal_step` True. Commit `97c157d` (first,
  insufficient attempt) + (uncommitted enhancement).
