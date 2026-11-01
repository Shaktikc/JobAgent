# Task 16 verification — 2026-10-31

**Verdict: not fully implemented according to the current specification.**
The normal skip and strong-match paths work in Chromium and on LinkedIn, but
three logic defects remain. Task 16 is **🟡 In progress** in both task files.

Reviewed the existing working tree at
`bc67d87d8af84b2a26a04547fb6942b95f84090b`, including the pre-existing uncommitted
Task 19 and status-overlay changes. No production code was changed by this
verification, and nothing was committed or pushed. Used
`.opencode/skills/incremental-implementation/SKILL.md` for incremental checks;
its referenced definition-of-done file was absent, so repository acceptance
criteria and `Agents.md` supplied the final verification requirements.

## Findings

| Priority | Bug | Reproduction and consequence |
| --- | --- | --- |
| P1 | BUG-089 | `choice=c1, fit=strong, ratings.c1=partial` proceeds to `open_form`. Missing ratings also pass. Conversely, `fit=partial, ratings.c1=strong` can skip the only strong candidate. Candidate ratings are not authoritative. |
| P2 | BUG-086 | `{"error":"upstream unavailable"}` is accepted as a match response and produces a clean skip. The unusable-response error/retry path is bypassed. |
| P2 | BUG-087 | With `allow_fallback=True`, a partial selection is used immediately rather than trying the remembered-resume/human fallback specified by Task 16 step 3. |

The first two defects are in `src/tools/resume_descriptions/messages.py`,
especially `parse_match`; the gate in `models.py` and
`src/tools/linkedin_resume_gate.py` trusts the resulting top-level fit. The
legacy issue is the early return in
`src/tools/linkedin_best_matching_resume/selection.py:189`.

Details and reproduction evidence are recorded in
[`task_16_bugs.md`](<../known Bugs/task_16_bugs.md>) and the
[`bug index`](<../known Bugs/bug_log.md>). These are controlled model-response
reproductions, not claims that the live LLM returned those contradictory replies.

## Verification results

- Focused unit checks: **195 passed**.
- Full suite: **656 passed, 62 skipped** using
  `uv run --frozen pytest -o addopts='' -q`.
- Lint: `uv run --frozen ruff check .` passed.
- Existing Task 16 Chromium tests: **3 passed**, enabled with
  `AUTOJOB_RESUME_GATE_LIVE=1`.
- Additional contract probes: **6 failing scenarios** cover the three defects
  above; ordinary partial, ordinary strong, and strong-alternative selection pass.
- Additional Chromium fixture: real match/next-job/open-form/fill code skipped
  an unmatched card, selected the next card, opened only the matched application,
  attached the resume, and reached the final step. The page recorded exactly
  one Easy Apply click and zero submit clicks. Model replies were controlled.

## Real LinkedIn check

The saved login worked. The check used the real search and selection code,
Easy Apply, and the Past week filter.

1. A deliberately empty resume pool made the selected Snowflake / AI Data
   Engineer job a no-match. The form stayed closed, no upload prompt appeared,
   and the next unapplied job was selected. This verifies the empty-pool
   acceptance case; it does not simulate an LLM rejection.
2. For **Artificial Intelligence Engineer — Allegis Group**, the configured LLM
   rated the existing Agentic AI resume strong and all other candidates partial.
   Matching finished before Easy Apply opened. Task 4 selected the listed resume,
   filled all three known fields, and reached **Review your application**.
3. `submitted=False`; the unsubmitted draft was dismissed and the verification
   browser closed. The existing bounded fresh-button retry handled a delayed
   Review transition successfully.

No application was submitted. Browser tests emitted the already-known Windows
asyncio closed-pipe shutdown warning (BUG-029); assertions and cleanup completed.

## Documentation correction

**BUG-088 is fixed:** Task 16 retained an obsolete default skip cap of 100.
Task 17 commit `b91c783` intentionally changed it to 0 (unlimited). Task 16,
Task 17, and the task index now describe that existing behavior consistently.
The runtime default was preserved.

## Local evidence

Artifacts are under `data/debug/task16_verification_20261031/` (git-ignored):

- `contract_probe.py` and `contract_results.json`: production parser, selector,
  gate, and routing reproductions.
- `browser_probe.py`, `fixture_results.json`, and `fixture.html`: controlled
  Chromium flow, click counts, resume attachment, and terminal-step evidence.
- `real_site_results.json` and `real_site_*.html`: real page DOM, job outcomes,
  ratings, routing, attachment, and cleanup results.
- `capture_review.py` captures the specific job page, using the project's
  existing page-specific screenshot helper. Initial `real_site_start.png`,
  `real_site_skipped_0.png`, `real_site_opened_1.png`, and
  `real_site_filled_1.png` captured a background browser tab and are not visual
  evidence of LinkedIn. Page-specific replacements use `*_page.png` names.
