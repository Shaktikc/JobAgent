# Task 20 validation recovery

Visible Easy Apply validation now receives one correction pass per blocked step
and one navigation retry. The current controls, error associations, allowed
choices, lengths, patterns and numeric bounds are discovered from the live form.
Required questions still follow Task 21: only their own visible `*` permits
filling. Optional inputs remain untouched.

Corrections normalize a supported value or ask the existing grounded chooser for
a concise equivalent. A second, conservative check requires all factual
components in order, allowing only grammatical filler to be removed. Changed
numbers, removed qualifiers/negation and omitted or new facts are rejected.
Unknown or unsafe corrections skip
instead of inventing answers. An unrelated unknown question keeps its normal
human-answer flow after rejected fields have been repaired. Re-renders receive
fresh control handles. Validation and character counters cannot change a
fillable step's identity; fieldless review content still distinguishes steps.

An unresolved validation is written to `data/invalid_input_skips.json` before
discarding the application. The file is a JSON array of metadata-only records:
timestamp, canonical job link/ID, available title/company, reason `invalid_input`,
field labels and redacted errors, correction attempted/retry count, and failure
reason. Existing entries are retained; the replacement document is flushed and
atomically installed. An unreadable journal is never overwritten. Older retired
`.jsonl` journals remain historical and are not modified by this feature.

A missing direct link, failed write, or failed close is a visible safe stop.
Validation outcomes bypass structural self-healing, including exceptions during
correction. A confirmed log plus modal cleanup produces `status="skipped"`, a
separate `Task20Outcome` count, and an append-only posting-ID exclusion. The
graph proceeds straight to `next_job`, never `await_submit`. The existing resume
gate still decides whether to open the newly selected job's form. Exclusions
survive pagination and date-range fallback and do not exclude another posting
merely because its title matches. Standalone job views return to filtered results
when necessary. Final application submission remains manual.

Implementation lives in `src/tools/linkedin_validation/` and
`src/state/validation.py`, with small hooks in the form walker, graph, next-job
loop, verification and CLI summary. All changed source files meet the 415-line
limit; existing untouched oversized files were left in place. The task files
remain in progress pending explicit user verification.

## Verification

Focused unit tests are `tests/unit/test_task20_*.py`. Chromium fixtures verify
recovery, persistent rejection, visible error scoping, counter-derived limits,
unknown-answer behavior, JSON-before-discard ordering, and selection of another
posting with an identical title. Existing Tasks 4/5/16/17/21 checks cover the
interrelated flows.

```powershell
uv run pytest
uv run ruff check .
uv build --wheel
$env:AUTOJOB_FILL_LIVE = '1'
uv run pytest tests/integration/test_task20_validation_live.py tests/integration/test_task20_continuation_live.py
```

On LinkedIn on 2026-11-02:

- The real nxzen form (`4485430037`) had four rejected required inputs, including
  long answers over its displayed 20-character bound. A known input was re-entered;
  no supported correction fit every field. The canonical link and failure details
  were saved to the JSON journal before closing/discarding the form. The existing
  next-job scan selected Software Engineer (`4485445868`) and preserved the Easy
  Apply/Past 24 hours filters, leaving its form closed for resume matching.
- In a separate verification run on the same posting, clearing a known required
  phone value triggered real LinkedIn validation. Production recovery restored
  exactly that known value and advanced from contact to the resume step. The
  applicant's number was kept in memory and omitted from the report.
- Neither run submitted an application. Screenshots and metadata evidence are
  gitignored under `data/debug/task20_linkedin/`: `walk.json`, `after.png`,
  `recovery.json` and `recovery.png`.

Repeat against the dedicated browser's current debugging endpoint:

```powershell
# Inspect only; --walk --continue-next exercises correction/skip/continuation.
uv run python -m scripts.verify_task20_linkedin --cdp-url http://127.0.0.1:2850
# Requires an open contact step with a prefilled required phone value.
uv run python -m scripts.verify_task20_recovery_linkedin --cdp-url http://127.0.0.1:2850
```

The baseline suite already fails
`tests/unit/test_self_heal_repair.py::test_main_builds_the_opencode_argv`: it
expects the previously removed `.opencode/skills/incremental-implementation/`
path. Task 20 does not alter or hide that unrelated failure. Some existing
Chromium runs also report a Windows asyncio pipe-cleanup warning after passing.
The implementation is committed and pushed; Task 20 remains in progress pending
user verification.

Final checks: 728 tests passed with the single baseline failure and 83 opt-in
skips. The 44 relevant Chromium checks passed when enabled (29 form/validation/
resume/choice checks plus 15 Task 21 checks). Ruff, compilation, wheel build and
the 415-line check passed. A source-archive build attempt was stopped during its
long workspace scan; the wheel was built separately and verified.
