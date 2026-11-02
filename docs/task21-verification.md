# Task 21 verification

The fill filter now keeps only controls with a visible `*` on their own question
label or group heading. It runs before answer selection, checkbox persistence,
human assistance and required-field accounting. HTML required flags and
`error-message-*` IDs cannot override an unstarred question.

`question_labels.py` supplies the visible labels for classic and SDUI markup.
Associated labels, legends, visible labelled-by nodes and local headings are
resolved without borrowing option text or another question's marker. Self-healing
reloads the helper and filter before their consumers.

## Automated checks

```powershell
.venv/Scripts/python.exe -m pytest --tb=short
$env:AUTOJOB_FILL_LIVE='1'
$env:AUTOJOB_REQUIRED_LIVE='1'
$env:AUTOJOB_VALIDATION_LIVE='1'
.venv/Scripts/python.exe -m pytest tests/integration/test_task21_required_labels_live.py tests/integration/test_task21_required_text_fields_live.py tests/integration/test_task21_optional_walk_live.py tests/integration/test_form_feedback_live.py tests/integration/test_fill_form_live tests/integration/test_checkbox_group_live.py tests/integration/test_choice_option_text_live.py --tb=short
uv build --wheel --out-dir data/debug/task21/dist
```

The default suite on 2026-11-02: **719 passed, 80 skipped, 1 failed**. The existing
failure is `test_self_heal_repair.py::test_main_builds_the_opencode_argv`, which
expects the already-deleted `.opencode/skills/incremental-implementation/SKILL.md`.
Task 21 does not change that repair-command test or restore the deleted skills.
Focused lint, compilation and the wheel build pass.

The combined live Chromium suite reports **38 passed**, covering both new Task 21
fixtures and existing form, checkbox, option-reader and Task 20 validation flows.
It also emits the existing Windows browser-process pipe-cleanup warnings.

Required fixtures in the existing unit/live form tests now include their actual
visible markers. The oversized test files were split by concern into
`tests/unit/test_browser_tools/` and `tests/integration/test_fill_form_live/`,
preserving all **114 unit tests and 14 live form tests**. Changed source files
remain below 415 lines.

## LinkedIn evidence and remaining check

The actual TikTok Additional Questions step was inspected on 2026-11-02. All three
unstarred groups carry misleading `error-message-*` described-by IDs. The starred
work-rights heading has a visible marker missing from its inputs' aria text.

Running the production `_fill_step` on that real page left **33 optional controls**
across gender identity, disability and ethnicity unchanged. No optional question
reached the chooser, unknown records, a human prompt or answer-store writes. The
starred work-rights question alone remained unknown. Evidence is gitignored:
`data/debug/task21/skip-check.json`, `skip-check.png`, `before-dom.json` and
`discovery-after.json`.

```powershell
.venv/Scripts/python.exe -m scripts.verify_task21_linkedin --cdp-url http://127.0.0.1:6172
```

The initial TikTok check could not advance without the human's work-rights answer.
Real navigation was subsequently verified on the reported Howden application as
described below. The verification script's `--walk` mode uses the normal
human-answer/navigation flow and stops before Submit; run it only when another
automation does not own the form. Never invent a work-rights answer for a test.

```powershell
.venv/Scripts/python.exe -m scripts.verify_task21_linkedin --cdp-url http://127.0.0.1:6172 --walk
```

Working-tree changes are uncommitted; base commit: `d732dc4`.

Task 20 was subsequently removed at the user's request on 2026-11-02. The Task 20
results below/above are historical; its source, state fields, tests and live
verification script no longer exist. Current checks use `test_form_feedback_live.py`
to verify that visible feedback does not prevent required answering or trigger
automatic job skipping. See [Task 20 removal](task20-removal.md).

## BUG-096 — starred salary questions skipped on Howden (2026-11-02)

Reported job: <https://www.linkedin.com/jobs/view/4485457082/>. Its salary,
software-engineering experience and notice-period questions all visibly carry
`*`. SDUI wraps each control and trailing helper paragraphs separately from the
preceding question. The local-label reader stopped at `0/20 0 of 20 characters`
(or `Invalid input` after validation), so filtering dropped the required field.

`question_labels.py` now accepts a local label only if it precedes the control
in DOM order. It continues climbing past trailing helper/counter paragraphs,
without changing the visible-asterisk policy or inheriting another question's
marker. The query injection, required filter, fill/ask callers and self-healing
reload order were reviewed and need no further changes.

`tests/integration/test_task21_required_text_fields_live.py` failed twice before
the fix with the reported counter-as-question symptom. Its five final browser
cases cover inputs, textareas, selects, automatic/human answers, helper markup
with/without test IDs, and ignoring helper asterisks on optional fields.

Verification results:

- 35 combined live Chromium tests passed across the new regressions, optional
  navigation, existing filling/checkbox/option handling and Task 20 validation.
  The existing 8 required-label browser cases also passed in the initial focused
  run. Existing Windows pipe-cleanup warnings remain.
- The default suite reported 719 passed, 82 skipped and the same pre-existing
  `test_main_builds_the_opencode_argv` failure described above. This run preceded
  the final three additional browser cases, which passed in the live run.
- Focused Ruff checks, compilation and `uv build --wheel --out-dir
  data/debug/task21/salary-dist` passed. The modified helper and new test file
  remain below 415 lines.
- On the exact LinkedIn job, production `_task4_on_page` navigated from the
  resume step to Additional Questions while preserving existing resume choices.
  All 7 required questions (11 controls) reached the answer chooser, including
  the three reported text questions. An intentionally unknown chooser left the
  answers blank; LinkedIn rejected Review and Task 20 stopped the walk.
- A separate production `_fill_step`/`ask_human_for_answer` check displayed the
  actual salary-answer banner. When no human answer arrived during its 10-second
  probe, salary remained a required unknown instead of being silently skipped.
  The saved salary `120` was not expanded into an invented annual amount.

Local evidence is gitignored: `data/debug/task21/reported-label-comparison.json`,
`reported-walk-unknown.json`, `reported-walk-current.json`,
`reported-salary-prompt.json` and `reported-salary-prompt.png`. Known answers fill
successfully in the live fixtures; completing the real application still needs
the human's actual answers. Task 21's filtering/answer-flow fix is verified and
marked done. No application was submitted.
