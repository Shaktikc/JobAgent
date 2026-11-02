# Task 20 — invalid-input correction and skips

The user authorized a correction-first replacement after the historical removal
described below. BUG-098 onward records the current implementation; the retired
entries and their original evidence remain intact.

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

### BUG-098 — validation text looked like a new form step

- **Symptom:** a real Chromium fixture counted a rejected Next as progress and
  clicked navigation three times instead of an initial attempt plus one retry.
- **Root cause:** the step identity hashed visible error feedback and character
  counters, so validation changed its signature without changing the actual step.
- **Fix:** fillable steps use progress/headings plus their control signature;
  fieldless review steps retain their text fingerprint. Exclude transient
  feedback/counters and preserve current reader seams in the test fakes.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/forms.py`, `src/tools/linkedin_validation/navigation.py`,
  `tests/integration/test_task20_validation_live.py` verifies exactly two Next
  clicks for success and persistent rejection; existing review/navigation tests
  pass. Commit: uncommitted by instruction; base `ad6dbda`.

### BUG-099 — unresolved input validation had no correction/log/continue path

- **Symptom:** rejected Easy Apply inputs could stop or enter structural recovery
  without preserving a usable posting link and continuing to another job.
- **Root cause:** the current walker/graph had no validation outcome, durable JSON
  journal, or posting-ID exclusion after the older Task 20 implementation's removal.
- **Fix:** one grounded correction pass and navigation retry; persist a flushed,
  atomic JSON record before discard; route confirmed skips directly to next-job
  selection, preserving ID exclusions across pages/date ranges. Log/close failures
  stop visibly without self-healing or marking an application submitted.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/`, `src/state/validation.py`, fill/
  next-job/verify nodes and graph; `tests/unit/test_task20_{journal,skip,flow,identity}.py`
  and `tests/integration/test_task20_continuation_live.py`. Real LinkedIn saved
  `https://www.linkedin.com/jobs/view/4485430037/` in
  `data/invalid_input_skips.json`, closed/discarded its form, then selected
  `4485445868` without submitting. A separate real required-phone rejection was
  corrected and advanced to the resume step. Evidence: `data/debug/task20_linkedin/`
  (`walk.json`, `recovery.json`, screenshots). Commit: `479be98`.

### BUG-100 — referenced character counters were omitted from input constraints

- **Symptom:** live LinkedIn reported a `555/20` counter, but the detector returned
  no maximum length, allowing an already-overlong value to be re-entered unchanged.
- **Root cause:** the bound was read only beside the input; LinkedIn's counter
  lives in the helper referenced by `aria-describedby`, outside that wrapper.
- **Fix:** read counters from associated feedback as well as the local control
  wrapper, before redacting values. Native maxlength still takes precedence.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/detection.py`;
  `test_detection_ignores_information_hidden_and_unrelated_text` covers a
  counter-only limit without a maxlength attribute; real nxzen inspection showed
  the same helper layout. Commit: `479be98`.

### BUG-101 — explicit error semantics were lost for unfamiliar wording

- **Symptom:** a visible `Enter a whole number` error was ignored when it lacked
  `aria-invalid` and did not match the detector's phrase list.
- **Root cause:** explicit `aria-errormessage` references and error severity were
  filtered through the same wording test as informational helper messages.
- **Fix:** honor visible field-associated error references/severity independently
  of wording, while generic informational feedback still needs a rejection signal.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/detection.py` and the real Chromium
  detection test's Notice field; hidden/unrelated/informational messages remain
  excluded. Commit: `479be98`.

### BUG-102 — validation first displayed after a navigation retry was missed

- **Symptom:** an initial swallowed click followed by a retry that first exposed
  validation ended as a generic stuck form instead of correction/logging/skip.
- **Root cause:** the retry inspected errors only if they existed before clicking.
- **Fix:** inspect after the generic retry, then allow the separate single
  correction pass/retry; never repeat either budget indefinitely.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/navigation.py`;
  `test_validation_appearing_only_after_generic_retry_is_corrected` in
  `tests/unit/test_task20_navigation.py`. Commit: `479be98`.

### BUG-103 — correction exceptions could lose validation context and self-heal

- **Symptom:** an exception during correction could replace the rejection with an
  empty form outcome and enter structural browser repair/relaunch.
- **Root cause:** correction and its final feedback read could raise before the
  validation outcome was assigned.
- **Fix:** retain the original rejection and a metadata-only correction failure;
  the normal journal/cleanup path handles it. Fill-node and fingerprint guards
  keep every validation outcome outside structural self-healing.
- **Status:** 🟢 Fixed.
- **Evidence:** correction/navigation modules, `src/nodes/fill.py`,
  `src/tools/self_healing/fingerprint.py`; raised-correction regression in
  `test_task20_navigation.py` and no-healing assertions in `test_task20_flow.py`.
  Commit: `479be98`.

### BUG-104 — a rejection prematurely aborted an unrelated human question

- **Symptom:** a correctable rejection in one field could cancel the normal
  human-answer flow for a different unknown required question.
- **Root cause:** the prompt guard treated any existing rejection as proof the
  pending unknown question itself had no valid correction.
- **Fix:** repair the actually rejected fields once, preserve an unrelated prompt,
  and retain its later navigation-retry budget. Re-enumerate a recovered current
  question instead of recording a model repair as a human-confirmed answer.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/correction.py`, form walker;
  `test_unrelated_unknown_question_keeps_human_flow_after_repair` plus existing
  human-answer tests. Commit: `479be98`.

### BUG-105 — a grounded alternative could still change an existing fact

- **Symptom:** a shorter stored salary could satisfy maxlength while changing the
  salary already present on the application.
- **Root cause:** source provenance alone does not prove the replacement is an
  equivalent correction of the existing answer.
- **Fix:** include the original answer as data in the constrained request and
  require every factual component in the same order, allowing only grammatical
  filler to be removed. Reject changed numbers, removed negation, omitted
  availability days/qualifiers, or new factual words.
  Unsafe or unsupported equivalents cause a logged skip rather than invention.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/{constraints,correction}.py`;
  `test_grounded_alternative_must_not_change_existing_salary_or_other_facts` in
  `tests/unit/test_task20_constraints.py`. Commit: `479be98`.
