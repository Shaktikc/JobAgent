# Task 5 — Ask the human for unknown answers, remember them, and show UI feedback

**Status:** ✅ Done

**Goal:** When the form asks a question the agent cannot answer with confidence,
pause and wait for the human's answer. Store the answer in the answer store so
Task 4's LLM can reuse it on a later run. While waiting, show a feedback message
in the browser UI saying that the agent does not know the answer.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and being filled.
- A writable answer store is available (e.g. `data/answers.json`).

**Inputs**
- The unknown question text (label, help text, and field type).
- The human's answer (entered interactively).

**Steps**
1. Detect a form question the agent cannot answer with confidence (the Task 4
   LLM could not decide it from the store, so the answer is unknown).
2. Show a feedback message in the browser UI stating that the agent does not know
   the answer (e.g. a visible banner/overlay near the field or modal).
3. Pause the run and wait for the human to provide the answer.
4. On receiving the answer, fill the field.
5. Save the question → answer mapping to the answer store.
6. Repeat for each subsequent unknown question.
7. Continue filling the form until all questions are answered or the run is
   stopped.

**Acceptance criteria**
- Unknown questions pause the run and wait for human input.
- A browser-UI feedback message clearly says the agent does not know the answer.
- The human's answer is stored, mapped to the question.
- When the same question later appears, Task 4's LLM answers it from the store
  with no further prompting.
- The answer store persists across runs.

**Notes**
- Store each answer against its question; Task 4's LLM matches questions by
  meaning, so an exact key wording is not required.
- Never overwrite an existing mapping silently; if the human changes an answer,
  record the update explicitly.
- The store must not contain credentials or other secrets.
- This task does **not** submit the application.
- **Task 12 extension:** a job-specific free-text question can be answered from
  the current job description + selected resume before this flow runs. When that
  context cannot ground an answer, the question still reaches this Task 5 flow and
  is saved here as usual. A generated context answer is never written to the store.
