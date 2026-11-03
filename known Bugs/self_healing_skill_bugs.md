# Self-healing — Repair skill lookup

### BUG-108 — Repair sessions omitted the incremental implementation skill

- **Symptom:** the full regression suite failed
  `test_main_builds_the_opencode_argv`: the repair command did not attach its
  required incremental implementation skill.
- **Root cause:** the wrapper hard-coded `.opencode/skills/.../SKILL.md`, but
  this checkout stores the skill under `.agents/skills/`.
- **Fix:** resolve the current `.agents` location first, with a fallback to
  `.opencode` for legacy checkouts. The wrapper uses that same path in its
  prompt and attachment list.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/self_healing/skill_path.py`,
  `scripts/self_heal_repair.py`, `tests/unit/test_self_heal_skill_path.py`, and
  the existing repair-command regression; full suite: 768 passed, 88 skipped.
  Fix is uncommitted, based on `128eb75`; no commit was requested.
