# Task 25: rejected-answer type conversion

Visible invalid-input feedback now tries a truthful number/text restatement
before Task 20's other correction options. This runs only for required questions
discovered on the current Easy Apply step. Answer lookup and the approved answer
stores are unchanged.

`linkedin_validation/type_conversion.py` recognises numeric types, input modes,
numeric patterns and bounds. LinkedIn also renders server-validated numeric
questions as ordinary text controls with none of those attributes. A rejected
single fact whose unit is explicitly present in the question can still be
restated numerically in that layout. No question, control identifier or step
position is hardcoded.

Supported examples include `2 years` → `2`, `5+` → `5` and `~3` → `3`. A rejected
bare number can become `2 years` when the question already supplies that unit.
Time units and explicit count questions supply context; ambiguous questions do
not. Multiple numbers, ranges, extra factual wording, negation, absent units and
different scales are declined. A conversion never chooses a range endpoint,
rounds a value, converts units or calls an LLM to invent wording.

The helper applies the discovered min/max, step, length and pattern constraints.
Step arithmetic uses exact rational values to avoid Decimal context rounding.
Before entry, recovery re-enumerates controls and checks the replacement input's
native validity on a detached copy, together with the discovered constraints.
Native number controls can erase invalid strings; the original entered literal
is recovered from the matching in-memory field record rather than treated as an
unknown required answer.

All available type repairs precede other fields' grounded correction calls.
Unconvertible values use the existing fact-preserving correction options. The
blocked step still receives at most one correction pass and one freshly
discovered Next/Review retry. Persistent rejection uses the existing durable
log/discard/skip path; it does not receive another navigation retry. Recovery
never clicks Submit application. Progress reports the conversion and confirms
acceptance when the same application advances.

`ValidationFailure` and `data/invalid_input_skips.json` include
`type_conversion_attempts`, an additive list of metadata-only records:

- `question`: the discovered question.
- `direction`: `text_to_number` or `number_to_text`.
- `attempted`: whether recovery actually tried entering a conversion.
- `outcome`: `not_possible`, `entry_failed`, `entered` (transient), `accepted`,
  `rejected` or `not_retried`.

Original and converted answers are omitted from these records. Older outcome
payloads load with an empty list. A successful conversion creates no skip record
or skipped-job count. Failure evidence survives exceptions, pre-prompt correction
and the normal navigation/cleanup paths.

## Verification

```powershell
uv run pytest
uv run ruff check .
uv build --wheel --out-dir data/task25-build
$env:AUTOJOB_FILL_LIVE = '1'
uv run pytest tests/integration/test_task25_conversion_live.py
```

The focused unit tests are `tests/unit/test_task25_{type_conversion,recovery,fallback}.py`.
They cover both directions, ambiguity, constraints and exact step precision,
conversion priority, grounded fallback, replacement-control constraints, bounded
navigation, persistent errors and metadata-only journal entries. Real Chromium
fixtures verify both directions, native number sanitisation, default text inputs,
DOM replacement, optional preservation and stopping before Submit.

On LinkedIn on 2026-11-04, the Bluebird posting `4484022219` rejected `7 years`
for “Years of commercial software engineering experience?”. This used the
applicant's approved existing value of `7`. The initial failed run exposed that
the control had only `type=text`, generic “Invalid input”, and a visible
20-character limit. After the fix, production recovery entered `7`, clicked
Review once, and reached “Review your application” in the same application.
The form remained open for manual submission; no skip was saved. The exact
`2 years` → `2` example is covered by the automated Chromium fixtures.

Private runtime evidence is gitignored under `data/debug/task25/`:
`conversion-before-fix.json`, `rejected.html`, `conversion.json`, `inspection.json`,
`inspection.png` and `browser-diagnostics.json`. CDP inspection also saw existing
LinkedIn-bundle React #418 and network console errors plus telemetry warnings;
the final conversion still advanced to review with no validation issues.
Repeat on an open question step in the dedicated browser:

```powershell
uv run python -m scripts.verify_task25_linkedin --cdp-url http://127.0.0.1:8074
# --prepare uses the existing approved-answer chooser; --next only clicks Next/Review.
uv run python -m scripts.verify_task25_linkedin --cdp-url http://127.0.0.1:8074 --prepare
uv run python -m scripts.verify_task25_linkedin --cdp-url http://127.0.0.1:8074 --exercise "Years of commercial"
```

The debugging endpoint changes when the browser restarts. The verifier restates
the field's actual existing number; it never injects a fabricated experience.
Task 25 remains in progress until the user explicitly verifies it.

Final checks: **879 passed, 123 opt-in checks skipped** in the full suite;
**13 passed** in the enabled Task 25/20/24 Chromium checks. Ruff, compilation,
wheel build and the 415-line check passed. Browser tests retain the existing
Windows asyncio pipe-cleanup warnings. Changes are uncommitted.
