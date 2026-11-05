# Completed human answers

Task 26 keeps unknown answers pending until a completion signal. Text supports change,
blur, Enter, or Done. Single choices commit on change/click; checkbox groups require
Done. The banner enables Done only when a valid non-empty answer is detected.

`AUTOJOB_SESSION_ASK_TIMEOUT_SECONDS` measures inactivity. Focus, edits, and ticks
extend the wait. Skip and inactivity discard pending input without storing or
returning it. Already committed, unfocused text can be adopted. The answer schema
and package exports remain unchanged. Task 24 recovery shares the same behavior.

The reader uses current control values and resolves group fallbacks after React
removes markers. The flow writes once after completion. The fill caller updates
its memory without repeating an identical disk write or replacing a confirmed
checkbox selection with later ticks. Prompt values and question echoes are rejected.

Verification:

- Default suite: 883 passed, 131 opt-in tests skipped.
- Dedicated Chromium suite: 15 passed. Cases cover slow typing, blur, Enter, Done, Skip, timeout,
  prefilled controls, single choice, multi-choice, marker loss and clearing.
- Real LinkedIn on 2026-11-05: Bluebird `4484022219`, commercial-experience question.
  Seven prefixes were checked over longer than the two-second inactivity setting;
  none was persisted. Done stored the complete answer once and displayed Saved.
  The wait returned and the original store/control were restored. No submission.
- The broader classic form fixture has a separate failure recorded as BUG-123.

Repeat against a prepared real text question:

```powershell
uv run python -m scripts.verify_task26_linkedin --cdp-url http://127.0.0.1:PORT --question "Years of commercial"
```

The script uses the field's existing approved fact, restores the store and field
in `finally`, and saves local evidence under `data/debug/task26/`. Run with no other
application run editing the answer store. Task 26 remains in progress until the
user verifies it, per Agents.md.
