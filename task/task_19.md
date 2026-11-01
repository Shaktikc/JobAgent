# Task 19 — Ignore years-of-experience requirements when matching a job

**Status:** ✅ Done

**Goal:** Make resume matching **experience-neutral**. The agent must never skip
or downgrade a job merely because the applicant has fewer years than the job
asks for. For example, if a job says **"10+ years of experience"** and the
selected resume has **7 years**, the resume is still eligible and can be rated
`strong`; the agent proceeds to Easy Apply as usual. Years of experience are
**not** a gate — the other core requirements (skills/technologies, domain,
responsibilities, scope) still decide whether the job is a genuine match.

This task does **not** change how years-of-experience **form questions** are
answered. Easy Apply questions such as "How many years of experience do you
have with Python?" keep using the existing Task 4.1/10/12 answer path and must
still be answered truthfully. The application is **never** submitted by this
task.

**Preconditions**
- Task 3.2 is implemented: every resume has an LLM profile and the LLM rates
  every candidate (`strong`/`partial`/`none`) and chooses the best strong match.
- Task 16 strict resume matching is the default gate.
- Resume profiles currently include `years_experience`, which is also used by
  Task 12 to answer job-specific form questions.
- `settings.llm` is configured. Matching remains LLM-only: an LLM failure still
  fails the run instead of falling back to a keyword scorer.

**Inputs**
- The open job's `JobDescription` (title, company, location, body, URL).
- Every resume's stored `ResumeDescription` profile (Task 3.2).
- The match prompt built by `build_match_messages`
  (`src/tools/resume_descriptions/messages.py`).
- No new environment setting: the experience-neutral rule is always on.

**Steps**
1. **Add an experience-neutral match view.** Put this in a new module,
   `src/tools/resume_descriptions/experience_policy.py` (split it into a package
   with a thin `__init__.py` if it would cross 415 lines):
   - `neutralize_experience_requirements(text: str) -> str` — remove or replace
     numeric years-of-experience **requirements** in the job text before the
     matcher sees them. Cover at least:
     - `10+ years of experience`
     - `5-8 years of experience` / `5–8 years`
     - `at least 8 years of experience`
     - `minimum of 5 years`
     - `10 yrs experience` / `10 years experience`
     - `experience required: 10 years`
     - `10 years of relevant/professional/industry experience`
     - `ten years of experience`
     - `10+ years of experience with Python` (keep `Python`; only neutralise
       the experience clause)
   - Preserve every non-experience requirement word in the same sentence. A
     transformation must not turn "10+ years of experience with Python and AWS"
     into text that loses `Python` or `AWS`.
   - Never mutate the original `JobDescription` or any resume file; work on
     copies.
   - `profile_for_match(description: ResumeDescription) -> dict` — return the
     profile as a dict **without** `years_experience`, so no numeric comparison
     can occur in the match prompt. The stored profile keeps the field for
     Task 12.
2. **Use the neutral view in the match prompt.**
   - `build_match_messages` must pass the sanitised job body and the profile
     dict without `years_experience` to the model.
   - Do not change the candidate ids, ordering, ratings schema, or parsing.
3. **Make the policy explicit in the match prompt.** Extend
   `_MATCH_SYSTEM_PROMPT` with a rule equivalent to:
   > Years-of-experience requirements are non-blocking. Never compare the
   > candidate's years of experience with a requested minimum or range, and
   > never rate a candidate `partial` or `none` because of a years shortfall.
   > If the candidate satisfies the core skills/technologies, domain, and
   > scope/responsibilities, rate it `strong` even when the job asks for more
   > years. Judge seniority from the scope and level of responsibilities, not
   > from a years count. Any years-of-experience figure left in the job text
   > (for example in company history) is not a fit criterion.
4. **Keep the Task 16 gate unchanged.** The gate still requires the LLM to
   rate a candidate `strong`. This task only changes the evidence the LLM
   judges: numeric years requirements are removed and `years_experience` is
   omitted from the candidate objects sent to the matcher. A candidate that
   lacks a genuine core skill or domain fit is still `partial`/`none` and is
   skipped as Task 16 requires.
5. **Record the policy in the audit trail.** Add a note to `Task3Outcome`
   and/or the match log line showing that years-of-experience requirements were
   ignored for the match. Do not record a years comparison or use one to
   justify a skip. The LLM's per-candidate ratings and rationale are still
   stored exactly as today.
6. **Keep the stored profile unchanged.** `ResumeDescription.years_experience`
   stays in `data/resume_descriptions.json`; only the match view omits it.
   Task 12 and the answer chooser continue to receive the full profile.
7. **Cover the edge cases.**
   - A job body with both a years requirement and a skill list: the years
     figure disappears, the skills remain.
   - A job body with no years requirement: text is unchanged.
   - A job body with a range or spelled-out number: neutralised.
   - A job body that mentions years in unrelated company history (for example,
     "we have served clients for 10 years") must not be treated as an
     applicant requirement; it must not make the match partial. Removing that
     figure from the match view is acceptable; keep the original description
     unchanged in state/logs.
   - The matcher must still rate a resume `partial`/`none` when it is missing a
     core skill, technology, or domain requirement.
8. **Do not change the strict gate itself.** Task 16's `strong`-only rule,
   skip accounting, and Easy Apply ordering stay exactly as they are. This task
   only changes the evidence the LLM considers when rating.
9. **Do not write years into or remove years from `answers.json`.** Form
   questions about experience are out of scope here.

**Acceptance criteria**
- A job that asks for more years than the selected resume has (for example
  `10+ years` vs `7 years`) is **not skipped for that reason**; the LLM can rate
  the resume `strong` and the run proceeds to Easy Apply.
- The match input sent to the LLM contains no `years_experience` profile field
  and no numeric years-of-experience requirement in the job text, while
  non-experience requirements (for example `Python`, `AWS`, `fintech`) are still
  present.
- The match system prompt explicitly states that years-of-experience
  requirements are non-blocking and must not lower a rating.
- A job whose resume genuinely lacks a core skill/technology/domain is still
  rated `partial`/`none` and skipped under Task 16 — the agent does not apply
  just because the years requirement is ignored.
- The original `JobDescription` and all resume files are unchanged; the stored
  profile still includes years for Task 12.
- Easy Apply form questions about years of experience still use the existing
  answer path unchanged (Tasks 4/5/10/12).
- No deterministic resume scoring is introduced; an LLM/matching failure still
  fails the run as required by Task 16.
- Unit tests, lint, and the required live-browser check pass; the live check
  proves a `10+ years` job with a 7-year resume is not skipped while a job
  missing a core skill still is.
- Never click **Submit application**; submission remains a manual human step.

**Notes**
- **No toggle.** This is unconditional. `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH`
  still controls whether a `strong` rating is required; this task only removes
  years from the evidence considered when producing that rating.
- **New module.** Add
  `src/tools/resume_descriptions/experience_policy.py` with
  `neutralize_experience_requirements(...)` and
  `profile_for_match(...)` (or equivalent names), and re-export the public API
  from `src/tools/resume_descriptions/__init__.py`. Do not grow
  `messages.py` (currently 341 lines) past the 415-line limit; move the
  match-view building into the new module if needed.
- **Conservative sanitising.** Remove only the years figure/requirement phrase,
  never the surrounding skill words. Unrelated company history is not turned
  into a requirement; the safest transformation is to drop the years figure
  from the match view while leaving the original text untouched.
- **Interrelated updates:** `src/tools/resume_descriptions/messages.py`,
  `src/tools/resume_descriptions/experience_policy.py`,
  `src/tools/resume_descriptions/__init__.py`, `README.md`, and their tests.
- **Task text sync (done at creation, per `AGENTS.md`):** Task 3 and Task 16
  were updated to describe the experience-neutral match so no older spec
  contradicts this task.
- **Tests:** add
  `tests/unit/test_resume_descriptions/test_experience_policy.py` covering
  each format above, preservation of skill words, unchanged text when no
  requirement exists, and the `profile_for_match` field omission; update
  `tests/unit/test_resume_descriptions/test_match.py` to assert the sanitised
  match messages and the prompt rule; keep the existing all-partial skip test to
  prove non-experience gaps still skip.
- **Live verification required:** run the real flow against a LinkedIn-shaped
  fixture with a `10+ years` requirement and a 7-year resume, confirm the resume
  is selected and the form opens/fills; then confirm a job missing a core skill
  is still skipped. Do not mark this task done from unit tests alone.
- **Bug log:** if implementation exposes a bug, add
  `known Bugs/task_19_bugs.md` and its row in `known Bugs/bug_log.md` with the
  symptom, root cause, fix, status, and evidence, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.
