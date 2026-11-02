# Task 20 removal

The user requested removal of all Task 20 code on 2026-11-02. Easy Apply no
longer treats visible validation feedback as a reason to automatically discard
an application, journal its link, or advance to the next posting. Required
questions retain their normal answer/human-prompt flow; Task 21 continues to
leave unstarred questions untouched. Existing stalled-form handling and manual
submission remain in place.

Removed components:

- The validation detection, journal, posting-identity and skip-handling package.
- The validation-specific outcome model, graph-state fields, serialized form
  rejection field, skip counters and command-line summary output.
- Checks before/during filling, human prompts and navigation, plus the fill-node,
  graph, verification, next-job scan and self-healing integration hooks.
- Task 20's dedicated unit/browser tests and LinkedIn verification script.

Shared state remains split into its existing package to preserve the public
`src.state` imports and the 415-line limit. The separate resume-match skip policy
and Task 21 label/filter changes remain in use. The task description, bug history
and existing runtime journals remain as historical records; active code no
longer reads or writes those journals.

`tests/integration/test_form_feedback_live.py` reproduced the old early stop
before removal and passes afterward: a starred salary field is filled despite
existing feedback, the optional input stays unchanged, navigation reaches review,
and Submit is never clicked.

Verification on 2026-11-02:

- The full suite reports 696 passed, 78 opt-in skips and one previously known
  failure: `test_main_builds_the_opencode_argv` expects an already-deleted
  `.opencode` skill path. No tests were skipped to hide that failure.
- 35 existing live Chromium checks pass across Task 21 required/optional labels,
  automatic/human answering, form navigation, checkbox groups and option text.
  The new feedback check also passes, for 36 successful browser checks.
- The existing graph and Task 16 tests pass (63 focused checks) after restoring
  the resume-match skip branch; BUG-097 records that intermediate regression.
- Repository Ruff checks, source compilation and the wheel build pass. The
  built wheel contains no validation-skip package or validation state module.
  An active source/test/script scan finds no remaining Task 20 references.
- On the user's exact LinkedIn job `4485457082`, the check dynamically navigated
  contact and resume screens, triggered real validation with one blank Review,
  then ran the normal form walker. Despite visible `Invalid input`, it reached
  the required human-answer prompt and stayed on the same application. All 11
  controls across 7 questions, including salary/experience/notice, retained
  their required labels. The verification was cancelled while waiting, without
  entering invented answers, submitting, discarding, or changing the journal.

Real-site evidence is gitignored:
`data/debug/removal_check/real-feedback-prompt.json` and
`data/debug/removal_check/real-feedback-prompt.png`.

Automatic approval review rejected recursive cache cleanup and the safer explicit
file list, reporting `blocked by policy`. Stale `.pyc` files remain under the
retired package's `__pycache__` and the related Python caches. They are excluded
from the verified wheel; all active source and integration hooks are removed.
The task stays in progress while cache cleanup/user verification is outstanding.

Working-tree changes are uncommitted; base commit `d732dc4`.
