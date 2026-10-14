# Task 6 — Bugs (skip jobs already marked "Applied")

Bugs whose root cause is in **Task 6**: skipping results cards already marked
**Applied** and opening the first unapplied job instead.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-020 | whole-page-Applied page stopped with no clear reason | 🟢 Fixed | `d9d571e` |

---

### BUG-020 — a whole-page-Applied page stopped with no clear reason

- **Symptom:** when every card on the page was already "Applied", the run stopped
  without explaining why (or risked opening one).
- **Root cause:** no explicit handling for the all-Applied case.
- **Fix:** skip Applied cards (`card_is_applied`, standalone word "Applied") and
  record a clear note when no unapplied job exists on the page; Task 7 then
  paginates.
- **Evidence:** `src/tools/linkedin.py` (`card_is_applied`),
  `src/tools/linkedin_job_selection.py`, `src/nodes/browse.py`. Commit `d9d571e`.
