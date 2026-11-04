# Task 23 — Use separate LLM models for Task 3 and Task 10

**Status:** 🟡 In progress

**Goal:** Allow Task 3 (resume descriptions and best-resume selection) and
Task 10 (matching or deriving answers from `data/answers.json`) to use different,
independently configurable LLM models. Changing either task's model must not
change the other task's model.

**Scope:** Task creation only is authorized now. Implementation and runtime
verification are pending. Specific model IDs have not been selected.

**Dependencies**
- Task 3's resume-description and resume-selection clients.
- Task 10's grounded answer chooser and Task 5's unknown-answer fallback.
- Task 14's existing general-purpose and self-healing model configuration.

**Inputs**
- A configurable model ID for Task 3.
- A separate configurable model ID for Task 10.
- Existing LLM credentials, base URL, timeout, and retry settings.
- `AUTOJOB_LLM_MODEL`, retained as the general-purpose model and compatibility
  default when a task-specific model is not configured.

**Steps**
1. Add task-specific model settings and environment variables for Task 3 and
   Task 10. Document their names and resolution order in `.env.example` and
   `README.md`. Reuse existing connection settings unless separately configured.
2. Resolve each task's model independently: its explicit override wins;
   an unset or blank override uses the existing general-purpose configuration.
   Never use the other task's override as a fallback.
3. Route Task 3's resume-description and best-resume-selection calls through
   its resolved model. Review shared resume-description callers, including
   Task 15's new-resume flow, so they use the same resume-purpose configuration.
4. Route Task 10's store-backed matching and derivation calls through its
   resolved model. Preserve provenance validation, cache behavior, and the
   Task 5 fallback when an answer is unsupported or the LLM is unavailable.
5. Preserve the general model for unrelated LLM work, including Task 12's
   job-context reasoning. When Task 12 wraps the Task 10 chooser, keep their
   model settings separate. Keep self-healing on its existing independent model.
6. Log each resolved task model without credentials so actual routing can be
   checked. A failed task-specific request must follow that task's existing
   error handling rather than silently switching to another model.
7. Update every affected caller, test, configuration example, and documentation
   reference. Add focused routing tests, then perform live verification with
   two distinct model IDs.

**Acceptance criteria**
- Task 3 and Task 10 can run in the same session using two different configured
  model IDs; request evidence shows each call uses the correct model.
- Changing either override affects only its intended purpose. Missing overrides
  preserve existing configuration behavior; unrelated and self-healing LLM
  routes retain their own settings.
- Resume matching, grounded answers, cache reuse, and unknown-answer handling
  continue to work, with focused tests and live-browser evidence.

**Verification**
- Unit tests cover independent overrides, unset/blank defaults, actual request
  model values, failure handling, and separation from Task 12 and self-healing.
- Run the affected configuration, resume, answer-chooser, and caller tests.
- In a real LinkedIn browser session, select a resume with the Task 3 model and
  answer a required Easy Apply question from stored knowledge with the Task 10
  model. Use a question that reaches the LLM rather than only a cache hit.
  Record both resolved model IDs and request evidence without credentials.
- Confirm an unsupported required question still reaches Task 5. Discover
  controls dynamically and leave the application for review without submitting.

**Implementation notes**
- This extends Task 14's routing with overrides for these two purposes; its
  general-purpose setting remains the default for all other non-healing work.
- Review `src/configuration.py`, `src/tools/resume_descriptions/`,
  `src/tools/llm_answer_reasoning.py`, `src/tools/llm_answers.py`,
  `src/tools/job_context_answers/`, and the form-walk callers and their tests.
- Put new routing logic in a new module, and keep edited source files within
  the 415-line limit. Update dependent imports and monkeypatch targets as needed.
- Log any bugs found and fixed during implementation under
  `known Bugs/task_23_bugs.md` and update `known Bugs/bug_log.md`.
- Mark this task 🟡 In progress in this file and the index when implementation
  starts. Mark it ✅ Done only after the user explicitly verifies it works.
