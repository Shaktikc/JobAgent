# Task 12 — Answer job-specific questions from the selected resume and job description

**Status:** ⬜ Not started

**Goal:** Keep the current job's description and the resume selected by Task 3
available as a per-job **context** while Task 4 fills the Easy Apply form. When
the form asks a free-text question about this job, this employer, or the
applicant's fit for the role — for example **"What attracts you to Propeller as
an employer?"** or **"What makes you a great candidate for this role?"** — answer
it from the **current job description** and the **selected resume** instead of
declaring it unknown. Every generated answer must be grounded in those two
sources, recorded with its evidence, and validated before it is filled.

The existing answer path stays in place: human-confirmed answers in
`data/answers.json` always win, normal questions are still answered by the
Task 4.1/10 store chooser (match or derive), and a question neither source can
ground is still deferred to **Task 5** for the human. The application is **never**
submitted by this task.

**Preconditions**
- Tasks 3 and 4 are complete: a job is open, its Easy Apply form is being filled,
  and Task 3 has selected a resume (`task3.selected_path`).
- The current job description is available in run state
  (`state["job_description"]`, also mirrored on `task3.job_description`).
- The selected resume is readable by
  `src.tools.linkedin_best_matching_resume.extract_resume_text` (PDF, DOCX, TXT,
  or MD) and/or has a stored Task 3.2 LLM profile in
  `data/resume_descriptions.json`.
- Task 4.1/10's answer chooser is wired (`src.tools.llm_answer_reasoning` and
  `src.tools.llm_answers`).
- An LLM is configured (`OPENROUTER_API_KEY` + `AUTOJOB_LLM_MODEL`). With no
  model, behavior is unchanged: job-specific questions go to Task 5.
- Task 5's ask-the-human flow works.

**Inputs**
- `JobDescription`: title, company, location, description body, and page URL.
- The selected resume path, its extracted text (read-only), and its stored LLM
  profile (summary, skills, titles, seniority, years of experience, domain).
- The current form question's context: label, help text, field type, and (for
  choice controls) the allowed options.
- The answer store (`data/answers.json`) and the Task 10 derived-answer cache,
  used for the precedence rules below.
- The LLM client (`LLMSettings`).

**Steps**
1. Build a **fresh per-job context** at the start of every Task 4 fill, and again
   whenever Task 11 reopens the same job. The context contains:
   - the current job description (title, company, location, body, URL);
   - the selected resume path;
   - the selected resume's extracted text, capped to a safe prompt size;
   - the selected resume's stored Task 3.2 profile.
   Never reuse the previous job's context. Resume files are only read, never
   modified, renamed, or moved.
2. Thread that context through the fill pipeline (`fill` node →
   `fill_application` → `_task4_on_page` → `_fill_step` → the answer chooser).
   Keep a small audit snapshot in run state/log (job title/company, resume path,
   character counts, available sources). The full resume/job text stays in
   memory and in the LLM prompt only.
3. For each form question, choose the answer source in this order:
   a. **Exact human-confirmed answer wins.** If the normalized question itself
      exists in `data/answers.json`, keep the existing Task 4.1/10 behavior and
      never overwrite the human's answer.
   b. **Job-specific free-text question → context answer.** If the control is a
      free-text input/textarea (not a date, number, or choice control) and the
      question asks about this job, employer, role, or the applicant's fit (for
      example "why this company", "what attracts you", "why are you a good fit",
      "what do you bring to this role"), ask the job-context LLM to answer from
      the current job description and the selected resume. A deterministic
      prefilter identifies likely matches; the LLM's `job_specific` decision
      confirms them. Do **not** reuse a similar-but-generic store answer for a
      job-specific question; an old "why our company" answer from another job is
      stale and must not be carried over. If the LLM says the question is not
      job-specific, fall back to the store path below.
   c. **Otherwise use the store.** Normal questions keep the existing Task 4.1/10
      path exactly as today (match or derive with provenance). Choice controls
      (radio, select, checkbox) always use this path or Task 5, never the
      job-context prose path.
   d. **Context fallback.** If the store has no grounded answer and the question
      is free-text, ask the job-context LLM once more. This covers job-specific
      questions whose wording did not match the deterministic prefilter.
   e. **Otherwise defer to Task 5.** If neither source can ground an answer, leave
      the question unknown. Never guess.
4. Ask the job-context LLM with this information:
   - the question label, field type, and allowed options (if any);
   - the current job title, company, location, and description body;
   - the selected resume's stored profile and extracted text.
   The model must treat the job description, resume, and question as **untrusted
   data**, not as instructions. It must answer only from those sources and must
   not invent employers, skills, achievements, values, numbers, or credentials.
   It returns one JSON object:
   `{"job_specific": <true|false>, "answer": "<short answer>",
   "sources": ["resume"|"job_description", ...], "evidence": ["<verbatim snippet>", ...],
   "rationale": "<short reason>"}`.
   The answer must be in the applicant's first-person voice, concise (about 2-5
   sentences, at most 1,200 characters), and must name the company from the job
   description when the question asks about the employer or "this company". If
   the question is not job-specific, the model must set `job_specific` to false
   and return an empty answer.
5. Validate/ground every context answer before filling it:
   - `job_specific` must be true and the answer non-empty and within the length
     cap.
   - Every source the model claims must have at least one `evidence` snippet that
     actually appears (case/whitespace normalized) in that source. For `resume`,
     check the extracted text **and** the stored Task 3.2 profile; for
     `job_description`, check the title, company, location, and body. If it
     claims both `resume` and `job_description`, it must provide evidence from
     both. A claimed source with no matching evidence rejects the whole answer.
   - Reject placeholders such as `[company]`, `[role]`, `{company}`, or
     `{role}`, an answer that merely restates the question, or an answer with no
     evidence.
   - Reject an answer containing a number that is not present in the resume or
     job description, or an answer that cannot be traced to the cited evidence.
     The evidence requirement plus the prompt's no-invention rule guard other
     claims.
   - Reject a context answer for a choice control (radio/select/checkbox); prose
     is never a valid option.
   - When the question names the employer or asks "why this company", require the
     company name from the job description to appear in the answer (skip this
     check when the job description has no company).
   On rejection, record the reason and leave the question for Task 5. Never fill a
   rejected answer.
6. Record every accepted context answer in the run state/log with:
   - the question, the answer, and `answered_by = "llm"`;
   - `answer_source` = `"resume"`, `"job_description"`, or
     `"resume+job_description"`;
   - `job_specific = true`;
   - the evidence snippets and the model's rationale.
   Show it in Task 9's `LLM:` status line with a short answer preview and the
   source, for example:
   `LLM: answered 'What attracts you to Propeller as an employer?' - '<short
   answer>' (from the job description + your resume)`.
7. Do **not** write generated context answers into `data/answers.json` or
   `data/derived_answers.json`. Those stores are for human-confirmed answers and
   Task 10 store derivations respectively. A generated job-specific answer is
   recomputed for each job and is never reused across jobs. If the human later
   answers the same question through Task 5, the normal Task 5 store path
   applies.
8. Repeat for each free-text question on each form step. Never apply a context
   answer to a choice control and never click **Submit application**. When the
   job changes (Task 8 opens the next job) or Task 11 resumes the same job,
   rebuild the context from the current job description and selected resume.

**Acceptance criteria**
- The selected resume text/profile and the current job description are available
  to the fill for every job, and a new job never inherits the previous job's
  context.
- A free-text question such as **"What attracts you to Propeller as an
  employer?"** is answered automatically from the current job description and
  selected resume, names the company, and cites evidence from the job
  description (and the resume when claimed).
- A free-text question such as **"What makes you a great candidate for this
  role?"** is answered from resume facts (and relevant job requirements) with
  evidence.
- Every generated answer is grounded: non-empty, length-bounded, cites existing
  evidence from each claimed source, and passes validation. Unsupported,
  placeholder, or untraceable answers are rejected, and an answer containing a
  number absent from the resume/job description is rejected.
- A non-job-specific question (for example salary, city, or work authorization)
  is **not** answered from the resume/job description; it still uses the store or
  Task 5 exactly as before.
- An exact human-confirmed `answers.json` entry still wins and is never
  overwritten.
- A job-specific question that cannot be grounded goes to **Task 5** rather than
  being guessed or answered from a stale similar store entry.
- Choice controls are never filled with prose.
- `answers.json` and `derived_answers.json` are unchanged by this task; generated
  answers live only in the run state/log.
- Task 9's panel shows the context source for each generated answer.
- The application is **not** submitted.

**Notes**
- **Proposed new modules (need human approval before creating):**
  `src/tools/job_context.py` for building/capping the per-job context, and
  `src/tools/job_context_answers.py` for the LLM call, grounding validator, and
  the context-aware `AnswerChooser`. If either file would exceed the 415-line
  limit, split it into a package with a thin `__init__.py` that re-exports the
  public API.
- Reuse `extract_resume_text` (Task 3) and the Task 3.2 description store
  (`load_descriptions` / `description_for`) — do not re-summarize the resume in
  this task, and never modify the resume file.
- Implement the context chooser against the existing `AnswerChooser` protocol so
  `field_filling._decide` keeps working. Wrap the existing Task 4.1/10 chooser
  instead of replacing it, preserving the store's match/derive provenance rules.
- **Interrelated updates required (keep the codebase consistent):**
  - `src/state.py` — add a `JobContext`/`JobAnswerContext` model and state/outcome
    snapshot; add `FormField.answer_source`, `FormField.job_specific`, and
    `FormField.context_evidence`; extend `QuestionDecision` with
    `context_sources` / `evidence` / `job_specific` fields (defaults keep the
    current Task 4.1/10 behavior unchanged).
  - `src/nodes/fill.py` — build the context from `task3.selected_path` and
    `state["job_description"]`; after self-heal recovery use
    `healing.description` and the same resume; pass it to `fill_application`.
  - `src/tools/browser.py` — extend `fill_application` and
    `run_full_agent`/`start_tasks` callers with the optional context parameter.
  - `src/tools/linkedin_easy_apply_fill/form_walk.py` — accept the context,
    build the context-aware chooser, and pass it to `_fill_step`.
  - `src/tools/linkedin_easy_apply_fill/field_filling.py` — keep `_decide`'s
    protocol; record the context source/evidence on the `FormField` and show it
    in the Task 9 status line.
  - `src/tools/self_healing/loop.py` — pass the same context through a healed
    retry of the same job so the reopen does not lose it.
  - `src/nodes/fill.py` log line — include the context source and evidence for
    each generated answer.
  - `README.md` — behavior, safety rails, and layout, so the new context source
    is documented.
  - `.env.example` — only if a new opt-out setting is added (for example
    `AUTOJOB_SESSION_JOB_CONTEXT_ANSWERS`, default enabled).
  - Task 4/5/10 notes that describe answers as coming only from the store need
    updating with human approval, because this task intentionally adds a second
    grounded source for job-specific questions.
- **Tests:** add a new unit test file for the context builder, prompt/parse,
  validation (resume-only, job-description-only, both, missing evidence,
  placeholder, unsupported claim, non-job-specific, choice-control rejection,
  missing context, and LLM failure), and the routing precedence (exact human
  answer wins; a job-specific question does not reuse a stale similar store
  answer; normal questions still use the store; ungrounded answers go to
  Task 5). Update the `fill_application` fakes in `tests/unit/test_graph.py` and
  `tests/unit/test_self_healing.py` for the new optional parameter. Add a
  live-browser regression test per `AGENTS.md`.
- **Live verification required:** after implementation, run the real LinkedIn
  flow and confirm in the browser that a job-specific question is filled from the
  selected resume/job description with the source shown in the Task 9 panel, and
  that a genuinely unsupported question still pauses for the human. Do not mark
  the task done from unit tests alone.
- **Bug log:** if implementation exposes a bug, record it in the appropriate
  `known Bugs/task_12_bugs.md` (ask for approval before creating the file) and in
  `known Bugs/bug_log.md`, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.
- The prompt and logs must not contain credentials or other secrets, and the full
  resume text must not be written to the log.

**Implementation order (bottom-up, easy to test):**
1. **Subtask 12.1** — Build and thread the selected-resume + job-description
   context.
2. **Subtask 12.2** — Ask the LLM to answer a job-specific question from that
   context, returning provenance.
3. **Subtask 12.3** — Ground/validate the context answer and route safely with
   Task 4.1/10 and Task 5.
4. **Main flow** (at the end of this file) — wire the context chooser into the
   fill path and verify it live.

## Subtask 12.1 — Build and thread the per-job context

**Status:** ⬜ Not started

**Goal:** Make the current job description and the resume selected by Task 3
available to the form-filling code as one immutable per-job context, without
changing any existing answer behavior.

**Preconditions**
- Task 3 selected a resume.
- The job description has been read into run state.

**Inputs**
- `JobDescription` from `state["job_description"]` (or
  `task3.job_description`).
- The selected resume path (`task3.selected_path`).
- The Task 3.2 description store.

**Steps**
1. Add a `JobContext`/`JobAnswerContext` model with job description, resume path,
   resume text, stored resume profile, and availability helpers.
2. Build it best-effort at fill time: read the resume text with
   `extract_resume_text`, load its stored Task 3.2 profile, and cap both the job
   body and resume text to safe prompt sizes. A read failure records an error on
   the context but never fails the fill.
3. Store the context on the run state (and a small audit snapshot on
   `Task4Outcome`) so later steps can explain which sources were available. Do
   not persist the full text.
4. Rebuild it for every job and every healed retry; never carry a previous job's
   context forward.
5. Pass it through `fill_application`, `_task4_on_page`, and `_fill_step`
   without changing any existing call site's default behavior (the parameter is
   optional).

**Acceptance criteria**
- A fill run receives exactly the selected resume and the current job
  description.
- A missing/unreadable resume or job body leaves the corresponding source
  unavailable without crashing the fill.
- The context is rebuilt for the next job and after a self-healed reopen.
- Existing callers/tests keep working with the parameter omitted.

**Notes**
- Resume files are read-only; the context builder never renames, moves, or
  modifies them.
- Cap the resume/job text so a long PDF or job page cannot exceed the model's
  context window. Include the stored LLM profile even when the raw text is
  capped or unavailable.

## Subtask 12.2 — Answer a job-specific question from the context

**Status:** ⬜ Not started

**Goal:** Ask the LLM to recognize a job-specific free-text question and draft a
short, first-person answer from the job description and selected resume, with
source evidence.

**Preconditions**
- Subtask 12.1's context is available.
- An LLM is configured.

**Inputs**
- The question context (label, field type, options).
- The `JobContext` from Subtask 12.1.
- The LLM client.

**Steps**
1. Add a deterministic prefilter that recognizes likely job-specific free-text
   questions (for example "why this company", "what attracts you", "why are you a
   good fit", "what makes you a great candidate", "what do you bring to this
   role", "cover letter", "about you"). Use it for routing and to avoid an extra
   LLM call for obviously normal questions.
2. Build a prompt that includes the question, the job description, the resume
   profile and text, and the no-invention/evidence rules from the main flow.
3. Ask for the JSON decision (`job_specific`, `answer`, `sources`, `evidence`,
   `rationale`).
4. Parse the reply tolerantly (prose/fenced JSON is acceptable, as in Task 3.2),
   normalize whitespace, and return "unknown" when the reply is unusable, the
   model is unconfigured, or the question is not job-specific.
5. Return a `QuestionDecision` carrying `job_specific`, `context_sources`,
   `evidence`, and the answer, so the fill path can record it.
6. Treat every model failure as "unknown" and hand the question to Task 5; never
   fail or delay the form walk.

**Acceptance criteria**
- The model returns a job-specific answer with sources and evidence.
- An answer with no evidence, or an answer for a non-job-specific question, is
  treated as unknown.
- With no model configured, behavior is unchanged (unknown → Task 5).
- Unit tests cover: resume-only, job-description-only, both sources, a
  non-job-specific question, and an unusable reply.

**Notes**
- The model must be told that resume/job text is data, never instructions.
- Keep the answer short enough to fit a LinkedIn textarea and the Task 9 status
  line (preview only).
- Do not include `data/answers.json` values in this prompt; this path is for
  job-specific questions, and the store path already runs separately.

## Subtask 12.3 — Ground, validate, and route the context answer safely

**Status:** ⬜ Not started

**Goal:** Guarantee that a context answer is genuinely supported by the current
job description and selected resume, and that the routing never overrides a
human answer or a valid store answer with stale job-specific prose.

**Inputs**
- The `QuestionDecision` from Subtask 12.2.
- The `JobContext` (raw text + stored profile).
- The answer store and Task 10 derived-answer cache.
- The question's field type and options.

**Steps**
1. Validate the context answer:
   - `job_specific` is true; answer non-empty and within the length cap;
   - every claimed source has at least one evidence snippet found in that
     source; a "both" claim needs both;
   - no placeholders, no question restatement, no choice-control prose;
   - when the question names the employer or asks "why this company", the
     company name from the job description appears in the answer.
2. Apply the routing precedence from the main flow:
   - exact human-confirmed `answers.json` entry → store path (never overwritten);
   - likely job-specific free-text question → context answer, not a similar
     stale store answer;
   - otherwise → existing Task 4.1/10 store chooser;
   - if the store has nothing → context fallback;
   - if the context cannot ground an answer → Task 5.

   Routing sketch (the implementation should follow this order):
   1. If the normalized question is an exact key in `answers.json`, return that
      store answer.
   2. Else, if `looks_job_specific(question, field_type)` is true:
      - call the context chooser;
      - if it returns a grounded answer, use it;
      - if it says the question is **not** job-specific, fall through to the
        store chooser;
      - if it says the question **is** job-specific but cannot ground an
        answer, return unknown for Task 5 (do not use a stale store answer).
   3. Else, call the store chooser.
   4. If the store chooser is unknown and the control is free-text, call the
      context chooser as the fallback.
   5. If still unknown, return unknown for Task 5.
3. On any validation failure, return "unknown" (Task 5) rather than filling a
   rejected answer, and record the rejection reason for the log.
4. On success, record the decision on the `FormField` (`answer_source`,
   `job_specific`, `context_evidence`, rationale) and in the Task 4 log. Do not
   write it to `answers.json` or `derived_answers.json`.
5. Keep the existing Task 4.1/10 and Task 5 behavior intact for every question
   this path does not handle.

**Acceptance criteria**
- A context answer with no existing evidence is never filled.
- A "both sources" answer is rejected unless it actually cites both.
- A placeholder or invented-looking answer is rejected and goes to Task 5.
- An exact human-confirmed answer is never overwritten.
- A normal question still uses the store path unchanged.
- The generated answer is recorded with source and evidence, and `answers.json`
  is unchanged.

## Main flow — Use the job context in the Easy Apply fill path

**Status:** ⬜ Not started

**Goal:** Wire Subtasks 12.1-12.3 into the existing fill path so a live LinkedIn
run answers job-specific questions from the selected resume and current job
description end to end.

**Steps**
1. In `src/nodes/fill.py`, build the `JobContext` from the current
   `task3.selected_path` and `state["job_description"]` before calling
   `fill_application`, and pass it through.
2. In `src/tools/linkedin_easy_apply_fill/form_walk.py`, build the context-aware
   chooser (wrapping the existing Task 4.1/10 chooser) when a model is
   configured; keep the existing chooser as the fallback when it is not.
3. In `src/tools/linkedin_easy_apply_fill/field_filling.py`, use the chooser as
   today and extend the Task 9 status line and `FormField` record with the
   context source/evidence when the answer came from the resume/job
   description.
4. In `src/tools/self_healing/loop.py`, pass the same context through a healed
   retry of the same job.
5. In `src/nodes/fill.py`'s audit log, include the context source and evidence
   for each generated answer; never log the full resume text.
6. Update `README.md` (behavior, safety rails, layout) and any interrelated
   Task 4/5/10 notes with human approval, so the documentation describes the
   new grounded source.
7. Run the unit tests and the live-browser check: a job-specific question is
   filled from the context with the source shown in Task 9, and a genuinely
   unsupported question still pauses for Task 5.

**Acceptance criteria**
- Running the live fill, a job-specific question ("What attracts you to
  Propeller as an employer?" / "What makes you a great candidate for this
  role?") is answered automatically from the current job description and
  selected resume (verified in the browser).
- A normal question is still answered by the store or Task 5 exactly as before.
- A question the context cannot ground still pauses for the human (Task 5) and
  is saved to `answers.json` as usual.
- Task 9's panel shows the `LLM:` line with the context source for a generated
  answer.
- The application is **not** submitted.
