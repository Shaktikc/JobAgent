# Task 25: rejected-answer type conversion

## BUG-118 — A truthful rejected answer is skipped before a type repair

- **Symptom:** `5+` and `~3` cannot be restated numerically, and a text control
  rejecting a bare number cannot receive wording implied by its question.
  Another field's correction can also run before an available type repair.
- **Root cause:** Task 20's limited normalisation has no explicit bidirectional
  conversion pass or conversion audit. It processes rejections in DOM order.
- **Fix:** Add conservative conversion and live-control modules, prioritise all
  safe type repairs before other corrections, reuse the single correction/retry
  budget, and retain metadata-only conversion outcomes in failure and skip
  records. Unconvertible answers retain the grounded fallback and safe skip.
  A conversion is marked accepted only after navigation actually advances.
- **Status:** 🟢 Fixed — automated and real-site verification passed; Task 25
  remains in progress pending user verification.
- **Evidence:** `src/tools/linkedin_validation/{type_conversion,conversion_flow,
  correction,navigation,skip}.py`, `src/state/{type_conversion,validation}.py`,
  `src/tools/linkedin_easy_apply_fill/form_walk/core.py`;
  `tests/unit/test_task25_{type_conversion,recovery,fallback}.py` and
  `tests/integration/test_task25_conversion_live.py`. Tests failed before their
  fixes. Real Bluebird recovery reached review without submission or a skip:
  `data/debug/task25/conversion.json`, `inspection.json`, `inspection.png`.
  Final suite: **879 passed, 123 opt-in checks skipped**; enabled Task 25/20/24
  Chromium checks: **13 passed**. Ruff, compilation, wheel build and source-file
  limits passed. Existing Windows pipe-cleanup warnings remain. CDP inspection
  sees LinkedIn-bundle React #418/network errors and telemetry warnings; the
  final real-site conversion still reaches review without validation issues.
  Commit: uncommitted, base `addac8f`.

## BUG-119 — Native number sanitisation bypasses conversion recovery

- **Symptom:** Chromium clears `2 years` entered into `type=number`. Recovery
  sees a blank required control and cannot convert the original entered fact.
- **Root cause:** Missing-answer routing relies on the sanitised DOM value;
  there is no conversion-aware check of the matching in-memory field record.
- **Fix:** Recover the entered literal from the record matched by question and
  control name, and route a provable conversion through invalid-value recovery
  before the missing-answer chooser. Keep default input types supported.
- **Status:** 🟢 Fixed.
- **Evidence:** `conversion_flow.py`, `correction.py`, `navigation.py`;
  the native-number Chromium case in `test_task25_conversion_live.py` failed
  with one click and an empty value, then passed with `2`, one recovery retry,
  a conversion audit, and no Submit click. Commit: uncommitted, base `addac8f`.

## BUG-120 — LinkedIn's numeric question has no numeric HTML metadata

- **Symptom:** Real Bluebird validation rejects `7 years`; the first Task 25
  implementation re-enters the same text and stays on the question step.
- **Root cause:** The actual SDUI control exposes only `type=text`, with no
  numeric input mode, pattern or bounds. The numeric rule exists server-side.
- **Fix:** For rejected single numeric facts, also use an unambiguous unit/count
  explicitly present in the discovered question. Preserve the same unit and
  all constraints; do not guess a unit from an unspecified experience question.
- **Status:** 🟢 Fixed.
- **Evidence:** `type_conversion.py`; the metadata-free numeric unit case and
  plain-text Chromium regression failed before the fix and passed after it.
  Real-site failure: `data/debug/task25/conversion-before-fix.json`; success:
  `conversion.json` and `inspection.png` show `7 years` → `7`, followed by
  review of the same posting `4484022219`, without submission or skipping.
  Commit: uncommitted, base `addac8f`.

## BUG-121 — Step validation can round away a forbidden fraction

- **Symptom:** `2.00000000000000000000000000001 years` passes a whole-number
  step check despite not being an integer.
- **Root cause:** Decimal subtraction/modulo use the default finite precision
  context, which can drop the fractional tail before checking the step.
- **Fix:** Use exact Fraction arithmetic for the shared numeric step check.
  Range checks and the original literal remain unchanged.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/constraints.py`;
  `test_constraint_checks_do_not_round_and_use_the_discovered_step_base` failed
  before the fix. The Task 20 constraint tests and Task 25 focused tests pass.
  Commit: uncommitted, base `addac8f`.
