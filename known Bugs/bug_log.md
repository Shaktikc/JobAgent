# Bug Log — master index

A single place that tracks every bug found in AutoJobApply and how it was fixed.
Bugs are split into one file per Task category, with a `general_bugs.md` file for
bugs that cannot be attributed to a single task.

Each entry records the **symptom** (what was observed), the **root cause**, the
**fix**, and the **evidence** (source, tests, and the commit(s)). Bug IDs are
stable — link to `BUG-NNN` from commits, PRs, or task notes.

- Status markers (at a glance):
  - 🟢 **Fixed** — the bug is fixed and guarded by a test/evidence.
  - 🟡 **Fixed (superseded)** — fixed once, but a later change replaced the first
    fix (check the current code, not just the entry).
  - 🔴 **Open** — known, not fixed yet.
  - ⚪ **Won't fix** — intentionally not fixed.
- New bugs go in the file for their task; if no single task owns the root cause,
  put it in [`general_bugs.md`](general_bugs.md).
- Keep newest entries at the bottom of each file so it reads chronologically.

## Files

| File | Scope |
|------|-------|
| [`task_1_bugs.md`](task_1_bugs.md) | Login, job search, "Try AI job search", Easy Apply filter |
| [`task_2_bugs.md`](task_2_bugs.md) | Select a job, find/click the Easy Apply button |
| [`task_3_bugs.md`](task_3_bugs.md) | Read the job description, pick the best resume |
| [`task_4_bugs.md`](task_4_bugs.md) | Fill the Easy Apply form, attach the resume, advance steps |
| [`task_5_bugs.md`](task_5_bugs.md) | Ask the human for unknown answers, remember them |
| [`task_6_bugs.md`](task_6_bugs.md) | Skip jobs already marked "Applied" |
| [`task_13_bugs.md`](task_13_bugs.md) | Date posted → "Past 24 hours" filter |
| [`self_healing_bugs.md`](self_healing_bugs.md) | Self-healing loop: auto-captured Easy Apply crashes, recovery, same-job resume |
| [`general_bugs.md`](general_bugs.md) | Browser session, profile/CDP, CLI, cleanup, build, security, tests |

> Task 7 (pagination) and Task 8 (await submit / next job) have no distinct root
> bugs of their own: their defects live in Task 2's list handling (BUG-019) and
> in the shared cleanup/session code (BUG-030).

## Quick index

| ID | Task / area | Symptom (short) | Status | Fix commit(s) |
|----|-------------|-----------------|--------|---------------|
| BUG-001 | General — browser session | browser-use killed the browser between pipeline tasks | 🟢 Fixed | `a175262` |
| BUG-002 | Task 4 — read | unreadable form silently looked empty → every field `NEEDS_REVIEW` | 🟢 Fixed | `24d381f` |
| BUG-003 | Task 4 — walk | fill only touched the first modal step (`1/4` pages) | 🟢 Fixed | `24d381f` |
| BUG-004 | Task 3 — read | `get_state_as_text` was dead after an agent run | 🟢 Fixed | `24d381f` |
| BUG-005 | Task 4 — evidence | no screenshot on a failed application | 🟢 Fixed | `14719e9` |
| BUG-006 | Task 5 — verify | unrecognized required fields dropped from review | 🟢 Fixed | `14719e9` |
| BUG-007 | General — tests | `Page.evaluate` needed the arrow-function form | 🟢 Fixed | `24ccc4a` |
| BUG-008 | General — tests | "applied today" test hard-coded a date | 🟢 Fixed | `2cd64a6` |
| BUG-009 | General — build | `poetry.lock` out of sync for a clean install | 🟢 Fixed | `43e55f1` |
| BUG-010 | General — security | candidate PII resumes committed to git | 🟢 Fixed | `4111f4d` |
| BUG-011 | Task 1 — search | "Try AI job search" button not clicked (markup/label) | 🟢 Fixed | `1dbb380`, `2dd5005`, `e5a7c7d` |
| BUG-012 | Task 1 — search | click navigated/reloaded, `Element.click()` looked failed | 🟢 Fixed | `4eee839`, `1dbb380` |
| BUG-013 | Task 1 — search | "many buttons clicked at once" on a half-loaded page | 🟢 Fixed | `48b4eb6` |
| BUG-014 | Task 1 — search | AI detour left zero job cards (semantic mode) | 🟡 Fixed (superseded) | `888e11d` → `9270f3a` |
| BUG-015 | Task 1 — search | "no page reload" rule was wrong | 🟡 Fixed (superseded) | `9270f3a` |
| BUG-016 | Task 1 — filter | Easy Apply **filter** confused with the blue apply button | 🟢 Fixed | (Task 1 filter fix) |
| BUG-017 | Task 2 — cards | AI/semantic job cards were `div[role=button]`, not found | 🟢 Fixed | `6d369f7` |
| BUG-018 | Task 2 — apply | fallback scan picked a job **card** as the apply button | 🟢 Fixed | `9ad31a9` |
| BUG-019 | Task 2/8 — list | stale card handles after a click → jobs silently skipped | 🟢 Fixed | `84b0bb5` |
| BUG-020 | Task 6 — skip | whole-page-Applied page stopped with no clear reason | 🟢 Fixed | `d9d571e` |
| BUG-021 | Task 3 — read | description read *after* Easy Apply → empty → LLM "none" | 🟢 Fixed | `7dce47d` |
| BUG-022 | Task 4 — form | inline hashed-class Easy Apply form not found | 🟢 Fixed | `84b0bb5` |
| BUG-023 | Task 4 — form | first matching modal was a hidden unrelated dialog | 🟢 Fixed | (Task 4 modal fix) |
| BUG-024 | Task 5 — ask | pre-filled controls (Email/Phone) wrongly asked about | 🟢 Fixed | `4eee839`/`99265a0` |
| BUG-025 | Task 5 — ask | empty "Use answer" silently marked the question skipped | 🟢 Fixed | `2b60465` |
| BUG-026 | Task 5 — ask | banner input vs. typing in the real form field | 🟡 Fixed (superseded) | `99265a0` |
| BUG-027 | General — profile | crashed run's stale lock → "exited before CDP became available" | 🟢 Fixed | `888e11d` |
| BUG-028 | General — profile | second launch force-killed a live browser → CDP drop (`WinError 1225`) | 🟢 Fixed | `888e11d` |
| BUG-029 | General — CLI | "I/O operation on closed pipe" noise after a successful run | 🟢 Fixed | `2b60465` |
| BUG-030 | General — cleanup | agent closed the browser on timeout (it must never close it) | 🟢 Fixed | `ef2ad44`, `31553e2` |
| BUG-031 | Task 3 — match | unread description treated as "no resume matched" | 🟢 Fixed | `7dce47d` |
| BUG-032 | Task 4 — walk | walk stopped at a field-less review step ("form did not advance") | 🟢 Fixed | (uncommitted) |
| BUG-033 | General — UI overlay | Task 9 status panel rendered behind LinkedIn's Easy Apply modal | 🟢 Fixed | (uncommitted) |
| BUG-034 | Task 4/10 — answers | "Experience on AI?" reported unknown despite the store covering it | 🟢 Fixed | (uncommitted) |
| BUG-035 | Task 4/5 — checkbox groups | a checkbox group was one question per option → the human's tick was never saved | 🟢 Fixed | (uncommitted) |
| BUG-036 | Task 2 — open the job | a job with Easy Apply was skipped as "no Easy Apply" (stale details pane) | 🟢 Fixed | `fdb6585` |
| BUG-037 | Task 5 — dropdown answers | a select prompt ("Select an option") was saved as the answer, then leaked into the next question | 🟢 Fixed | (uncommitted) |
| BUG-038 | Task 3 — match | resume match hung for minutes / failed as "unusable match reply" | 🟢 Fixed | `1ca5311` |
| BUG-039 | Task 3 — read | job title read as "0 notifications" → weak resume match | 🟢 Fixed | `1ca5311` |
| BUG-040 | Task 2 — pane | every clicked job "did not open" (search-query tab title) | 🟢 Fixed | `f928866` |
| BUG-041 | Task 8 — loop | advanced to the next job without a real submission | 🟢 Fixed | `f928866` |
| BUG-042 | Task 4 — walk | stopped at Review before the next step rendered; optional unfilled field failed the run | 🟢 Fixed | `e5a21a2` |
| BUG-043 | Self-Healing — import | state ↔ tools import cycle broke graph test collection | 🟢 Fixed | (uncommitted) |
| BUG-044 | Self-Healing — bug log | repeated fingerprint crashed on Windows backslash paths | 🟢 Fixed | (uncommitted) |
| BUG-045 | Self-Healing — bug log | index update overwrote symptom/status columns | 🟢 Fixed | (uncommitted) |
| BUG-046 | Self-Healing — reopen | same-job reopen ignored non-HTTP job URLs | 🟢 Fixed | (uncommitted) |
| BUG-047 | Self-Healing — reopen | failed reopen left the new browser holding the profile | 🟢 Fixed | (uncommitted) |
| BUG-048 | Task 4 — walk | one swallowed Next click stopped the walk as "form did not advance" | 🟢 Fixed | (uncommitted) |
| BUG-049 | Self-Healing — evidence | failure screenshot captured the active tab, not the failing page | 🟢 Fixed | (uncommitted) |
| BUG-050 | Task 11 — trigger | stuck walk with an already-listed resume never started self-healing | 🟢 Fixed | (auto-recorded) |

| BUG-051 | Self-Healing — fill | form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopp | 🔴 Open | (pending) |

| BUG-052 | Task 4/11 — required field | SDUI required question read as optional → walk stuck as "form did not advance" | 🟢 Fixed | (uncommitted) |

| BUG-053 | Self-Healing — fill | a human-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (uncommitted) |
| BUG-054 | Task 8 — loop | post-apply "resume to profile" promo modal not closed → no next job | 🟢 Fixed | (uncommitted) |

| BUG-055 | Task 4 — fill | a human-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (uncommitted) |

| BUG-056 | Task 4 — SDUI walk | heading/page root before controls + uncommitted city typeahead → false "advance", no resume attached | 🟢 Fixed | (uncommitted) |

| BUG-057 | Task 4 — fill | an LLM-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (auto-recorded) |

| BUG-058 | Task 4 — required-only | optional (no `*`) diversity questions were asked/filled and paused the run | 🟢 Fixed | `2d26b71` |
| BUG-059 | Task 4/5 — SDUI checkbox group | group question read as each option's text, and the human's ticks were never saved | 🟢 Fixed | `2d26b71` |
| BUG-060 | Task 8 — submit detection | real submission not detected (SDUI dialog + wrong card) → stuck on "waiting for you to submit" | 🟢 Fixed | (uncommitted) |
| BUG-061 | Task 8 — submit wait | closing the browser during the wait left the run hung forever | 🟢 Fixed | (uncommitted) |

| BUG-062 | Self-Healing — fill | form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopp | 🔴 Open | (pending) |
| BUG-063 | Task 8 — pagination | stopped on page 1 when the remaining unapplied cards had no Easy Apply instead of advancing | 🟢 Fixed | (uncommitted) |
| BUG-064 | Task 11 — crash guard | a crash outside `fill` (e.g. `next_job`) ended the run and self-healing never ran | 🟢 Fixed | (uncommitted) |

| BUG-065 | Self-Healing — browse/search | returned Task 1/2 failure could not close the failed browse browser, and was mis-filed as a fill exception | 🟢 Fixed | (uncommitted) |
| BUG-066 | Task 7/8 — pagination | new hashed-class pagination controls were missed, then the run stopped without task-level self-healing | 🟢 Fixed | (uncommitted) |
| BUG-067 | Task 9/11 — input lock | human mouse/keyboard could change the page while the agent was working | 🟢 Fixed | (uncommitted) |

| BUG-068 | Self-Healing — next job/pagination | results pagination could not advance: CDP click swallowed; now falls back to a DOM click, then a direct `start=25` URL navigation | 🟢 Fixed | (uncommitted) |

| BUG-069 | Self-Healing — next job/pagination | retry still stopped on pagination; self-healing classifier/capture/buglog were not reloaded after repair | 🟡 Fixed (superseded) | (uncommitted) |
| BUG-070 | Self-Healing — repair agent | autonomous repair asked a file-split approval question, exited 1, and stopped the loop | 🟢 Fixed | (uncommitted) |
| BUG-071 | Task 13 — Date posted | a checked "Past 24 hours" radio was accepted though the results URL was not filtered | 🟢 Fixed | (uncommitted) |
| BUG-072 | Task 3 — read | AI/search job view read "Are these results helpful?" + the job list as the job | 🟢 Fixed | `55a7838` |

## Template for new entries

Add the entry to the file for its task (or `general_bugs.md`), and add a row to
this index.

```markdown
### BUG-NNN — <short title>

- **Symptom:** <what was observed / how it reproduced>
- **Root cause:** <the underlying defect>
- **Fix:** <what changed>
- **Status:** 🟢 Fixed | 🟡 Fixed (superseded) | 🔴 Open | ⚪ Won't fix
- **Evidence:** <source files, tests, and commit(s)>
```
