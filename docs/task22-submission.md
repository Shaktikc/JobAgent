# Task 22 — Application submission choice

Before an interactive agent run starts, the CLI asks whether you will submit
applications manually or the agent should submit them automatically. Press Enter
for manual submission, or choose option 2 for automatic submission for this run.
The date-range prompt comes first. Task 18's search-query prompt is still a
separate task; `--query` continues to set the job search.

Use `--submission-mode manual` or `--submission-mode auto` to select explicitly.
Without this flag, non-interactive runs use manual mode. EOF, interrupted input,
and three invalid answers also select manual. Maintenance commands skip the question.
LangGraph callers can set `submission_mode="auto"` in `new_state(...)`; its default
is `"manual"`. The graph retains this field across job changes and fill recovery.

Manual mode preserves the review/human-submit workflow. In automatic mode, the
agent finishes the existing dynamic form walk, checks the fill outcome and current
required answers, and requires one enabled terminal submit control on LinkedIn's
jobs page. It checks site validation and native control validity before clicking.
Only a new submission confirmation or a new Applied status counts as success.
The confirmed job then uses Task 8's normal accounting, cap, and next-job loop.

The confirmation baseline is read before clicking so immediate success is detected.
`AUTOJOB_SESSION_AUTO_SUBMIT_TIMEOUT_SECONDS` defaults to 30 seconds. A missing
confirmation, browser failure, or ambiguous control stops the loop and leaves the
browser open for manual review. The action is never replayed by self-healing.
The outcome records `submission_attempted` before clicking and `submitted` only
after confirmation. Fill recovery can still run before submission and retains
the selected mode.

Submission first scrolls the terminal control into view, then checks readiness
and clicks once. Confirmation recognizes re-rendered semantic cards, including
the `Selected,` prefix and `(Verified job)` badge, and matches the job's title and
company. Other jobs' Applied badges and pre-existing submitted statuses never
confirm the current attempt.

Resume selection and the Upload resume button also scroll into view before
their click coordinates are calculated. A long saved-resume list previously
caused the upload click to miss, leaving `resume=none` and stopping the run
before automatic submission. This attachment fix applies to both submission modes.

An uncertain or blocked automatic attempt ends with `status="needs_review"`
(CLI exit code 1). Submit failures save JSON metadata and a screenshot under
`data/debug/task22/`; the run log includes the evidence path. JSON stores boolean
submission signals, control geometry, and resource paths/statuses; it excludes
application answers and confirmation prose. This does not trigger another click.

Implementation lives in `src/submission_choice.py`,
`src/tools/linkedin_auto_submit.py`, and `src/nodes/submission_guard.py`, with
integration into the existing CLI, state, graph, and apply-loop node.

Verification uses unit regressions plus isolated live Chromium forms with varying
step counts, runtime blockers, and absent confirmation. Controlled fixtures send
no real applications. A real LinkedIn inspection checks the current DOM and
submission preflight separately; a genuine job submission requires choosing
automatic mode for that run. Task 22 remains in progress until user verification.

Final manual review releases the renderer input lock before asking you to act,
including the fallback path that waits for you to close the browser. A timeout,
cancelled wait, or failed observation leaves the retained page interactive.
Confirmed manual submission restores the automation lock before the next job.
Pending status-panel lock installation is drained before handoff, and a cancelled
unlock finishes before cancellation propagates, so neither can re-lock review.
Each pending-install and final unlock wait is limited to 15 seconds if the
browser connection stops responding; cancellation cannot wait indefinitely.

The shared browser entry point is now the `src/tools/browser/` package. Its thin
`__init__.py` preserves existing imports and lazy Task 1–5 exports. `runs.py` owns
the run registry and final human handoff; `orchestration.py` drives the tasks;
`profiles.py`, `primitives.py`, and `queries.py` retain their existing behavior.
Regression patches target the module that calls each dependency.

The live LinkedIn inspection opened a real Easy Apply contact step, discovered
its Next control, and confirmed that automatic submission was blocked before the
terminal step. It left the application open without filling or submitting it.
Screenshots and metadata are under `data/debug/task22/` (gitignored).

The reported CORTO posting (`4486453355`) was inspected after the timeout and
already showed Application submitted. Its selected-card markup was used to
extend the Chromium regressions. That submitted application was not sent again.
