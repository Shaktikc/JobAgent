# Task 29 — Log every discarded Easy Apply form with a pre-discard screenshot

**Status:** ✅ Done

**Reported problem**

- The automation sometimes closes an open Easy Apply form **without submitting
  it** — for example when Task 20 skips an application whose answers cannot be
  validated, or when a form is left open after a self-heal/retry and has to be
  discarded before the next job is opened.
- After the discard the draft and the answers in it are gone. The only durable
  evidence today is Task 20's `data/invalid_input_skips.json`; other discard
  paths only print a line in the terminal.
- The user wants every discarded Easy Apply form kept in a **`discard_log`**
  file, so they can see which jobs were abandoned, why, what step the form was
  on, and what answers had been entered.

**Goal**

- Every time the automation closes an **open** Easy Apply form without
  submitting it, append exactly one record to `data/discard_log.json`.
- The record must identify the job and the discard reason, and include a
  snapshot of the form's current step: visible questions, controls, filled
  values, and resume choices.
- Immediately **before** clicking the first close/discard control, take a PNG
  screenshot of the open form and save it under `data/debug/discards/`, then
  reference it from the record.
- The record must also say whether the form was actually closed or the close
  failed, so a stuck form can be reviewed manually.
- Screenshotting and logging are durable and best-effort: they must be bounded,
  never change the close behaviour, never crash the run, and never block the
  discard when they fail.

**Definition of "discarded" for this task**

Included:

- A form is open when `close_easy_apply_form` is called, and the automation
  clicks **Dismiss / Close / X**, then **Discard / Discard application** when
  LinkedIn asks for confirmation.
- The close attempt fails (for example the modal is stuck): the discard is
  still logged with `"closed": false`, because the job was abandoned.

Excluded:

- A job skipped before Easy Apply was ever opened (Task 16's normal no-resume
  match). There is no draft to discard, so no record is written.
- A submitted application, the post-submit "Your application was sent..."
  dialog, and post-apply **Not now** modals.
- The human manually clicking Discard on a form the agent left open for manual
  submission. The automation does not observe that click. (A DOM watcher for
  manual discards can be a follow-up task if wanted.)
- Closing the browser with a form still open; that is a release, not an
  explicit discard.

**Scope**

- A new discard-log module, the close helper that all automation discards go
  through, its two production callers, tests, and README documentation.
- No change to which jobs are skipped, when a form is opened or closed, or to
  the existing terminal/panel text.
- Log field values locally only. Never print form values to the terminal or the
  status panel.

**Preconditions**

- `close_easy_apply_form` in `src/tools/linkedin_resume_gate.py` is the single
  production choke point for automation discards.
- Task 4's dynamic form readers exist: `read_form`, `read_resume_info`, and
  `read_apply_modal`.
- Task 2/Task 20's job identity helper `current_job_link` exists.
- `data/` is runtime state and is already git-ignored.

**Target file and format**

- Primary file: **`data/discard_log.json`** (created on the first discard).
- Format: a UTF-8 JSON **array of objects**, pretty-printed with `indent=2` and
  a trailing newline, so it can be opened directly in an editor.
- Append-only: existing records are never rewritten, truncated, or deleted.

Record shape (fields may be empty strings / empty lists when unavailable):

```json
{
  "timestamp": "2026-11-17T09:41:22.123456+00:00",
  "run_id": "…",
  "job": {
    "id": "4401234567",
    "url": "https://www.linkedin.com/jobs/view/4401234567/",
    "title": "Senior Software Engineer",
    "company": "Acme"
  },
  "reason": "invalid_input",
  "source": "task20_invalid_input",
  "form": {
    "modal_title": "Apply to Acme",
    "step": "step identity from read_form()",
    "step_title": "…",
    "fields": [
      {
        "question": "Are you legally authorized to work in the United States?",
        "kind": "radio",
        "type": "radio",
        "name": "urn:li:fsd_formElement:…",
        "required": true,
        "checked": true,
        "value": "",
        "selected_text": "",
        "option": "Yes",
        "options": []
      }
    ],
    "resume": {
      "options": [{"label": "resume.pdf", "checked": true}],
      "select": null,
      "file_input": false,
      "selected": "resume.pdf"
    },
    "text_excerpt": "You have 1 of 4 steps complete…",
    "snapshot_error": ""
  },
  "screenshot": {
    "path": "data/debug/discards/discard-20261117-094122-123456-4401234567.png",
    "error": ""
  },
  "close": {
    "closed": true,
    "attempts": 1,
    "discard_button_used": true,
    "discard_prompt_seen": true,
    "error": ""
  },
  "details": {
    "validation_issues": [],
    "notes": ""
  }
}
```

**Steps**

1. **Create `src/tools/linkedin_discard_log/` as a package.**
   - `models.py` — the record/snapshot shapes (Pydantic models or typed
     dictionaries matching the JSON above).
   - `capture.py` — build a record from the live page and optional caller
     context.
   - `screenshot.py` — capture and save the pre-discard PNG.
   - `store.py` — append a record durably.
   - `__init__.py` — thin re-exports (`record_discard`, `append_discard`, model
     names). Keep every module well under the 415-line limit.

2. **Capture the form before it is closed.**
   - Reuse the existing readers; do not duplicate their JavaScript:
     - `read_form(page)` → `(open, title, fields, step)`;
     - `read_resume_info(page)` → resume options/select/file input/upload
       button;
     - `read_apply_modal(page)` → open state and modal text;
     - `current_job_link(page, state)` → canonical job id/URL.
   - Prefer job title/company from `state["job_description"]` and
     `state["task2"]`; fall back to the details pane/DOM and then to the values
     the caller passes in.
   - Copy each field's current values as they are at discard time: question,
     kind, type, name, required, checked, value, selected text, selected option,
     and options where the control exposes them.
   - This is a snapshot of the **current visible step** only. Do not click
     through previous/next steps, and do not wait longer than the normal form
     read.
   - Bound the record: at most 100 fields; clip question/value/selected text to
     1,000 characters; clip the modal excerpt to 4,000 characters. Record the
     truncation in `details.notes`.
   - Mask values for obviously sensitive questions (password, SSN/social
     security, bank account, credit card) as `"[redacted]"`. The log is local,
     but it must never store those answers.
   - Any capture failure must produce a still-usable record with
     `form.snapshot_error` set; it must never abort the close.

3. **Take the screenshot immediately before the discard.**
   - Capture the PNG after the form snapshot and **before the first close /
     dismiss click**, while the Easy Apply form is still fully visible. Never
     take it after the discard starts.
   - Use the page-level screenshot (`page.screenshot()`, base64 PNG), not the
     session/active-tab screenshot, so a background tab or another open page
     cannot produce a misleading image.
   - Wrap the call in a short timeout (for example `asyncio.wait_for(...,
     timeout=5)`) and decode/write the PNG under
     **`data/debug/discards/`**.
   - File name:
     `discard-<UTC yyyymmdd-hhmmss-microseconds>-<job_id or "unknown-job">.png`.
     Use `settings.debug_dir / "discards"` so the path follows the existing
     debug-artifact convention, and create the folder on demand.
   - Save the path in `screenshot.path` on the discard record. On any failure,
     set `screenshot.error` to a concise message and keep the path empty.
   - If the form is already showing a **Discard application?** confirmation at
     entry, the screenshot must still be taken first and will show that prompt.
   - Screenshot failure must be bounded and must never block or change the
     close; the form snapshot and discard proceed regardless.
   - Never print or attach the screenshot to the terminal/status panel; it is a
     local review artifact and can contain personal answers.

4. **Append durably without losing existing records.**
   - Use a process/thread lock plus the existing atomic-write pattern
     (temporary file in the same directory, flush/fsync, `os.replace`), like
     `src/tools/linkedin_validation/journal.py`.
   - Create `data/discard_log.json` on the first record.
   - If the existing file is not a JSON array of objects and cannot be read,
     never overwrite it: rename it to
     `discard_log.corrupt-<UTC-timestamp>.json`, then start a fresh log with the
     new record. Report this in the run log.
   - If the write itself fails, report a concise line through `notify` and
     continue the close. A missing log entry is unfortunate; a blocked discard
     is worse.

5. **Log inside `close_easy_apply_form`.**
   - Open-state check first: if no Easy Apply form is open, return `True` as
     today, write **no** record, and take **no** screenshot (prevents
     duplicates when a previous step already closed the form and `next_job`
     calls it again).
   - If a form is open, capture the snapshot and then the screenshot **before**
     clicking any close control.
   - Track and record:
     - number of close attempts actually used;
     - whether a **Discard application?** confirmation was seen;
     - whether the **Discard** button was used;
     - the final `closed` boolean and any error.
   - Use optional keyword-only context arguments with safe defaults so every
     existing positional caller keeps working:
     `reason`, `source`, `state`, `run_id`, `job`, `extra`/`details`.
   - Default `reason` to `"unspecified"` and `source` to the caller's name when
     none is supplied.
   - Persist one record after the close attempt, whether it succeeded or not.
   - Emit one concise `notify` line after a successful save, for example:
     `Task 29: discard logged for "Senior Software Engineer" (invalid_input) -> data/discard_log.json`.
     Do not include field values.
   - Never let capture, serialization, or file I/O raise out of the close
     helper or alter its `True`/`False` return value. Logging must be fully
     best-effort.

6. **Pass meaningful context from the production callers.**
   - `src/tools/linkedin_validation/skip.py` (`persist_and_close`, Task 20):
     - reason `invalid_input`, source `task20_invalid_input`;
     - pass `state`, `run_id`, the captured `job_id`/`job_url`/title/company,
       and the validation issues/correction/type-conversion attempts in
       `details`.
   - `src/tools/linkedin_apply_loop.py` (`open_next_job`, `close_form=True`):
     - reason `leftover_form`, source `next_job`;
     - pass `run_id`, `skip_title` as the job title when available, and the
       page-captured job id/URL.
     - This call runs after a self-heal/retry or a Task 16 skip. A normal Task
       16 skip has no open form, so it writes nothing; a Task 20 close that
       already succeeded is also a no-op here. Never write a duplicate.
   - Update `scripts/verify_task24_linkedin.py` and any test helper only if the
     new keyword arguments require it; their positional calls must continue to
     work.

7. **Update and extend the tests.**
   - New `tests/unit/test_task29_discard_log.py` covering:
     - a first record creates a valid JSON array;
     - a second record appends without altering the first;
     - an unreadable file is quarantined (never deleted/overwritten) and the
       new record is still written;
     - capture includes the current step, required/checked/value/option data,
       resume choices, and job identity;
     - sensitive questions are redacted;
     - a capture failure still yields a record with `snapshot_error` and the
       close still succeeds;
     - a PNG is written under the test data dir and `screenshot.path` points to
       a non-empty file;
     - the fake page proves the screenshot was taken **before** the first close
       click (for example by recording a `screenshot-then-click` event order);
     - a screenshot failure leaves `screenshot.path` empty, sets
       `screenshot.error`, and still writes the record and closes the form;
     - a write failure is reported but `close_easy_apply_form` still returns
       the same result and never raises.
   - Extend `tests/unit/test_task16_resume_gate.py`:
     - closing an open form writes exactly one record with
       `closed: true` and never clicks **Submit application**;
     - a stuck form writes `closed: false`;
     - an already-closed form writes no file and takes no screenshot;
     - existing click-order assertions remain unchanged.
   - Extend `tests/unit/test_task20_skip.py`:
     - the Task 20 path writes one record with reason `invalid_input`, the job
       link, and the validation details.
   - Point every test at `tmp_path` (existing `_settings(tmp_path)` helpers
     already do) so tests never pollute the real `data/discard_log.json`.
   - Update any fake page that needs to answer the extra form-reader queries;
     keep its existing click behaviour.

8. **Document the log and screenshots.**
   - Add a short "Discard log" section to `README.md`: the log path, when a
     record is written, that it is local/git-ignored, that it contains the
     current form step plus answers, and that each discard has a PNG in
     `data/debug/discards/` taken immediately before the discard.
   - Do not edit other task files.

9. **Live browser verification (required).**
   - Run the real close harness that already opens and discards a live Easy
     Apply form:
     `uv run python scripts/verify_task24_linkedin.py`.
   - Confirm:
     - the form closes without **Submit application** being clicked;
     - `data/discard_log.json` is valid JSON and gains exactly one new record;
     - the record has the real job id/URL/title, the expected reason/source,
       the current step, at least one visible field when the form had fields,
       and `close.closed: true`;
     - `screenshot.path` points to a real PNG under `data/debug/discards/`;
     - open the PNG and confirm it shows the **open Easy Apply form just before
       the close**, not the results list or a blank/background tab;
     - the terminal shows the concise Task 29 line.
   - Then run a normal live flow (`uv run autojob --no-dry-run`) until at least
     one real skip/discard path is exercised, and confirm no duplicate records
     are created when `next_job` runs afterwards.
   - If a live run reveals a bug, log it in `known Bugs/task_29_bugs.md` and add
     the row to `known Bugs/bug_log.md` with symptom, root cause, fix, status,
     and evidence. Create the file without waiting for approval.

**Acceptance criteria**

- Every automation discard of an **open** Easy Apply form appends exactly one
  record to `data/discard_log.json`, including failed closes with
  `"closed": false`.
- No record is written when no form was open, when the job was skipped before
  the form opened, or when an application was submitted.
- Each record identifies the job, run, reason, source, current form step,
  visible fields/values, resume choices, and close outcome.
- Each actual discard also has a non-empty PNG under
  `data/debug/discards/`, captured **before** the first close/discard click,
  and the record's `screenshot.path` points to it. The PNG clearly shows the
  open form, not another tab or the results list.
- Screenshot failure is reported in `screenshot.error` but never blocks the
  snapshot, the log write, or the close.
- Capture is dynamic: it works for a radio/select/file-input resume control and
  for any current step without assuming a fixed form layout.
- A capture, screenshot, or write failure never blocks or changes the close
  result; the run reports it instead.
- Existing discard records are never lost; an unreadable file is preserved
  under a timestamped name.
- Sensitive values are redacted and no form values are printed to the terminal
  or the status panel.
- Existing tests, the new tests, lint, and the live-browser check pass. A
  passing unit test alone does not complete this task.
- The task is marked 🟡 **In progress** when work begins and stays so until the
  user explicitly confirms it works.

**Implementation notes**

- Primary files:
  `src/tools/linkedin_discard_log/models.py`,
  `src/tools/linkedin_discard_log/capture.py`,
  `src/tools/linkedin_discard_log/screenshot.py`,
  `src/tools/linkedin_discard_log/store.py`,
  `src/tools/linkedin_discard_log/__init__.py`,
  `src/tools/linkedin_resume_gate.py`,
  `src/tools/linkedin_validation/skip.py`,
  `src/tools/linkedin_apply_loop.py`,
  `tests/unit/test_task29_discard_log.py`,
  `tests/unit/test_task16_resume_gate.py`,
  `tests/unit/test_task20_skip.py`, and `README.md`.
- Keep imports light: import the form readers lazily inside the capture module
  if a top-level import would create a cycle; `linkedin_resume_gate` is already
  imported by the validation skip path.
- Do not change `_MODAL_BUTTON_SELECTORS`, the label allow-lists, the attempt
  count, or the click order in `close_easy_apply_form`. The new record and
  screenshot are evidence, not a new automation decision.
- Take exactly **one** screenshot per discard, immediately before the first
  click, outside the retry loop. Use `page.screenshot()` rather than the
  session's active-tab screenshot (see the BUG-048 note in
  `src/tools/self_healing/capture.py`), wrap it in a short timeout, and swallow
  every failure.
- The screenshot is local evidence and can contain personal answers; keep it
  under git-ignored `data/debug/discards/` and never show it in the terminal,
  panel, or README.
- Reuse `current_job_link` rather than duplicating job-URL parsing; when the
  form is already a "Discard application?" confirmation, the snapshot may have
  no fields, but the job identity and modal excerpt must still be logged.
- Check interrelated code: every caller of `close_easy_apply_form`, the
  validation-skip tests' monkeypatch targets, self-heal/reopen cleanup, and the
  Task 29 store's atomic writer.
- Keep every file under the 415-line limit; split a module if it grows past it.
- Test command examples:
  `uv run pytest tests/unit/test_task29_discard_log.py tests/unit/test_task16_resume_gate.py tests/unit/test_task20_skip.py -q`
  and the full suite/lint before reporting readiness.
- Mark Task 29 ✅ **Done** in this file and `task/task.md` only after the
  implementation works, the live-browser check passes, and the user explicitly
  confirms it.
