# Task 20 — invalid-input skips

The user requested removal of all Task 20 code on 2026-11-02. The feature's source,
state fields, integration hooks, tests and verification script have been removed;
the entries below preserve the original bug history and evidence. The former
fixes are superseded by intentional feature removal, documented in
`docs/task20-removal.md`. Existing runtime journals are preserved as historical
data and no longer read or written by the application. No commit was authorized.

### BUG-091 — rejected applications retried instead of being logged and skipped

- **Symptom:** nxzen's Senior AI Engineer posting (`4485430037`) showed four
  visible `Invalid input` errors. A stalled step could retry Next, enter the
  structural self-healing path, or stop without preserving a usable job link.
- **Root cause:** the form walker compared step signatures without checking
  visible field validation; the graph had no validation-skip outcome. A detected
  rejection also needed to remain terminal if LinkedIn removed its message
  during a re-render.
- **Fix:** detect visible errors within the current Easy Apply surface before
  filling/asking, after filling, around navigation, and while polling a stalled
  step. Keep a detected rejection terminal. Append and fsync metadata-only
  records before closing/discarding the form; stop safely on write or cleanup
  failure. Track skips separately from submissions and route directly to the
  existing next-job scan. Restore filters when returning from a standalone job.
- **Status:** 🟡 Fixed (superseded) — Task 20 removed by user request on 2026-11-02.
- **Evidence:** `src/tools/linkedin_validation_skip/`,
  `src/tools/linkedin_easy_apply_fill/`, `src/nodes/fill.py`, `src/graph.py`,
  `src/nodes/apply_loop.py`, `src/nodes/verify.py`, and `src/state/`.
  Automated coverage: `tests/unit/test_validation_skip_*.py` and
  `tests/integration/test_task20_validation_live.py`. The Chromium walker test
  proves one rejected Next click and no Submit click. Live LinkedIn saved
  `https://www.linkedin.com/jobs/view/4485430037/` in
  `data/invalid_input_skips.jsonl`, closed the rejected form, and selected another
  posting without submitting. Final continuation/filter evidence:
  `data/debug/task20_linkedin_verification.json` records AI Product Engineer
  (`4484576495`), zero applications submitted, and the next form left closed
  for the existing resume-match gate. Commit: uncommitted by instruction;
  base commit `d732dc4`.

### BUG-092 — semantic job cards reopened the rejected posting

- **Symptom:** the first live continuation check saved/closed nxzen correctly
  but selected the same `4485430037` posting again.
- **Root cause:** LinkedIn's semantic cards contain no posting anchor or classic
  `data-job-id`; their `componentkey="job-card-component-ref-4485430037"`
  attribute carries the identity. Title matching also cannot distinguish two
  postings with the same title.
- **Fix:** read semantic component keys as well as classic IDs/URNs/anchors,
  carry rejected posting IDs through the append-only run state, and exclude
  them before clicking cards across pages and date ranges. The verification
  script asserts that the selected posting ID differs from the rejected one.
- **Status:** 🟡 Fixed (superseded) — Task 20 removed by user request on 2026-11-02.
- **Evidence:** `src/tools/linkedin_validation_skip/identity.py`,
  `src/tools/linkedin_job_selection.py`, `src/tools/linkedin_apply_loop.py`;
  `tests/unit/test_validation_skip_selection.py` checks identical titles and
  reordered cards. The real Chromium component-key regression failed before
  the fix and passes after it. Live LinkedIn selected Automation & AI
  Integration Developer (`4484826034`), then the standalone-return check selected
  AI Product Engineer (`4484576495`), preserving the original rejection journal.
  Commit: uncommitted by instruction; base commit `d732dc4`.

### BUG-093 — informational field feedback triggered a false validation skip

- **Symptom:** a real Chromium fixture containing `Your email stays private`
  beside a field was reported as a validation error.
- **Root cause:** the generic `artdeco-inline-feedback__message` class was
  interpreted as error severity, although LinkedIn also uses it for information.
- **Fix:** generic feedback must contain a validation rejection or have an
  explicit error/invalid control signal. Visibility checks reject hidden,
  transparent, and unrelated content; echoed answer values are redacted within
  the browser before metadata is returned.
- **Status:** 🟡 Fixed (superseded) — Task 20 removed by user request on 2026-11-02.
- **Evidence:** `src/tools/linkedin_validation_skip/detection.py`;
  `tests/integration/test_task20_validation_live.py` reproduces informational
  feedback, hidden errors, unrelated text, visible rejections, and answer
  redaction in real Chromium. Commit: uncommitted by instruction;
  base commit `d732dc4`.

Validation on 2026-11-02: repository lint passes; full offline suite has
696 passed, 70 opt-in skips, and one unrelated existing failure,
`test_main_builds_the_opencode_argv`, which references the already-deleted
`.opencode/skills/incremental-implementation/SKILL.md`. Those pre-existing
skill deletions and the repair launcher are outside Task 20's changes.

### BUG-097 — removing the fill skip also removed the resume-match skip route

- **Symptom:** during Task 20 removal, unmatched resumes incorrectly routed to
  opening Easy Apply instead of the next job. Existing graph and Task 16 tests
  caught three failures before this change was reported ready.
- **Root cause:** the match and fill routers shared the same `status == skipped`
  branch text; an insufficiently scoped deletion removed the match branch.
- **Fix:** restore `_route_after_match`'s Task 16 branch and remove only the
  Task 20 branch from `_route_after_fill` and its graph edges. The separate
  resume-match skip policy remains unchanged.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/graph.py`, `tests/unit/test_graph.py`,
  `tests/unit/test_task16_partial_match.py`: 63 focused tests passed. The final
  full suite has 696 passed, 78 browser skips and the previously documented
  unrelated `.opencode` skill-path failure. Commit: uncommitted by instruction;
  base commit `d732dc4`.
