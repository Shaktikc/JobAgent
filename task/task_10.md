# Task 10 — Answer similar questions from the answers.json knowledge base

**Status:**

**Goal:** When the Easy Apply form asks a question that is **similar** to something
already in the answer store (`data/answers.json`), the LLM should **answer it from
that stored knowledge** instead of declaring it unknown and asking the human again.
Today the LLM (Task 4.1) may only **copy a stored answer string** that already
answers the question; it cannot use a related stored entry to answer a newly-worded
question, so it wrongly hands the question to Task 5 even though the human already
taught the agent what it needs.

The motivating example: the form asks **"Experience on AI? [Yes/No]"**, while the
store already contains
`"how many years of work experience do you have with artificial intelligence (ai)": "5"`.
No stored value is literally `"Yes"`, so Task 4.1 cannot select one and the question
is reported as *"AutoJobApply does not know this answer"* — even though the answer
("Yes") is plainly **entailed** by the stored knowledge. Task 10 lets the LLM
**match *or derive*** the answer, always grounded in and citing the store, and never
inventing facts. When nothing in the store supports an answer, the question still
goes to Task 5 as unknown.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and its fields are enumerated.
- Task 4.1 works today: the LLM classifies each question and can select a stored
  answer by meaning (`src.tools.llm_answers`).
- Task 5 works today: unknown questions pause for the human and are stored in
  `data/answers.json`.
- An LLM is configured (`OPENROUTER_API_KEY` + `AUTOJOB_LLM_MODEL`). With no model,
  behaviour is unchanged: questions are unknown and go to Task 5.
- The answer store is available via `src.tools.answers.load_answers`.

**Inputs**
- Each question's context: label, help/placeholder text, field type, and (for
  choice controls) the allowed options.
- The answer store entries (normalized question → answer).
- The LLM (text model) used to classify the question and answer it from the store.

**Steps**
1. For each enumerated field, build the question context (label, help text, field
   type, option labels) — unchanged from Task 4.1.
2. Give the LLM the store (question → answer) and ask it to answer the current
   question in **either** of two ways:
   a. **Match:** copy a stored answer whose meaning answers the question (what
      Task 4.1 does today, e.g. "City" → stored `enter city or location`).
   b. **Derive:** produce a short answer that the stored entries **entail** when no
      single stored value can be copied verbatim — for example a Yes/No answer
      implied by a stored "years of experience" or "do you have …" entry.
3. Require **provenance**: the model must cite the stored key(s) (`source_keys`) it
   used and give a short rationale. An answer with no cited, existing source is
   rejected (unknown).
4. Validate and normalise the answer:
   - every cited `source_keys` entry must exist in the store;
   - the answer must be non-empty, and for a choice question must map to one of the
     question's listed options (a yes/no derive must be a yes/no synonym);
   - a derive that fails validation is rejected rather than filled.
5. **If a grounded answer is chosen** (matched or derived): fill the field, record
   the decision (question, answer, whether matched or derived, source keys,
   rationale) in the run state/log, and show it in Task 9's `LLM:` status line with
   the source ("answered … - 'Yes' (derived from '… (ai)': '5')").
6. **If nothing in the store supports an answer:** leave the field for **Task 5** to
   ask the human and remember it. Never guess.
7. Repeat for each field; never overwrite an existing mapping silently, and never
   click **Submit application**.

**Acceptance criteria**
- A Yes/No question whose answer is entailed by a stored entry is answered from the
  store — not reported unknown. (Concrete case: "Experience on AI? [Yes/No]" is
  answered **Yes** from the stored AI years-of-experience entry.)
- A similar-but-rewritten question with an equivalent stored answer is answered by
  meaning (already true; must keep working).
- Every answer is **grounded**: it either copies a stored value or cites the stored
  key(s) it is derived from; an answer with no existing cited source is never used.
- The LLM **never invents** an answer or uses outside knowledge: a derived answer
  must be supported by the cited stored entries, and a choice answer must map to one
  of the question's options.
- A question the store genuinely does not cover is still deferred to **Task 5** as
  unknown rather than guessed.
- Each decision is explainable and recorded (matched/derived, chosen answer, source
  keys, rationale) and surfaced in Task 9's panel.
- The application is **not** submitted.

**Notes**
- **Relaxes Task 4.1's "select-only" rule, carefully:** Task 4.1 said the model may
  *only ever select among stored answers*. Task 10 keeps the guarantee that the model
  cannot fabricate a source (it must cite existing keys) while allowing it to
  **derive** an answer those entries entail. The no-invention rule is preserved.
- **Safety over coverage:** when in doubt, defer to Task 5. A wrong auto-answer is
  worse than asking. Derives are limited to values cleanly entailed by the store
  (e.g. positive years ⇒ "Yes" for an experience question); cross-meaning guesses
  (e.g. reading "full, unrestricted working rights: No" as *not* legally authorized
  without checking) must not be made.
- **Untrusted content:** question text and stored values are untrusted data — pass
  them as data only, never as instructions, and set any UI text with `textContent`.
- **Do not block:** a slow/failed LLM call leaves the question unknown and hands it
  to Task 5; it must never fail or delay the run.
- The store and prompts must not contain credentials or other secrets.
- Keep every file under the 415-line limit; split into a package if needed.

**Implementation order (bottom-up, easy to test):**
1. **Subtask 10.1** — Ask the LLM to answer from the store (match *or* derive) and
   return provenance.
2. **Subtask 10.2** — Ground and validate a derived answer (cited sources exist;
   choice answers map to options; never invent).
3. **Subtask 10.3** — Remember derived answers so the same question is instant and
   consistent next time (without polluting the human-confirmed store).
4. **Main flow** (at the end of this file) — wire the reasoning chooser into the fill
   path so Task 4/5 use it.

## Subtask 10.1 — Answer from the store's knowledge (match or derive), with provenance

**Status:** 

**Goal:** Extend the question-answering call so the model may not only copy a stored
answer but also **derive** a short answer the stored entries entail, always returning
the stored key(s) it used.

**Preconditions**
- Task 4.1's chooser exists (`src/tools/llm_answers.py`) and is wired into
  `src/tools/linkedin_easy_apply_fill/` (`form_walk.py` builds it; `field_filling.py`
  `_decide` calls it).

**Inputs**
- The question context (text, field type, options) and the answer store.
- The LLM client (`LLMSettings`).

**Steps**
1. Add a decision shape that records provenance: the existing `QuestionDecision`
   gains `source_keys: list[str]`, a `derived: bool`, and keeps `answer`,
   `category`, `rationale`, `question` (proposed new module + fields — see Notes).
2. Update the system prompt: the model may (a) copy a stored answer that answers the
   question, or (b) **derive** a short answer that the cited stored entries entail;
   it must return `{"category", "answer", "source_keys", "rationale"}`. It must
   never use outside knowledge and must list every stored key it relied on.
3. Pass the full store as before (it is small); keep the existing "match by meaning"
   behaviour for the copy path.
4. Parse the reply; resolve a **copied** answer against the store as today, and keep
   a **derived** answer only if it carries at least one existing `source_keys` entry.
5. When no model is configured, or the reply is unusable, return "unknown" so the
   question flows to Task 5 unchanged.

**Acceptance criteria**
- The model can return a derived answer together with the stored key(s) that support
  it, and a copied answer with its matching key.
- An answer with no existing cited source is treated as unknown.
- With no model configured, behaviour is unchanged (unknown → Task 5).
- Unit tests cover: a copy decision, a derive decision with sources, and a derive
  with no/unknown sources being rejected.

**Notes**
- **Approved** new module: `src/tools/llm_answer_reasoning.py` (a
  `ReasoningAnswerChooser` implementing `AnswerChooser`, plus
  `build_reasoning_answer_chooser`), and **approved** test file
  `tests/unit/test_llm_answer_reasoning.py`.
- Keep `src/tools/llm_answers.py`'s existing chooser intact so the change is
  additive and the old behaviour can be A/B-tested.

## Subtask 10.2 — Ground and validate a derived answer (never invent)

**Status:** 

**Goal:** Guarantee that a derived answer is actually supported by the store and fits
the field, so the LLM can never fill an invented or off-option value.

**Inputs**
- The `QuestionDecision` from Subtask 10.1 (answer + `source_keys` + rationale).
- The store, the question's field type, and its allowed options.

**Steps**
1. Reject any decision whose `source_keys` is empty or references a key not present
   in the store — no provenance means no fill.
2. For a choice control (radio/select), require the final answer to map to one of the
   question's options (a yes/no derive must canonicalise to the option label, e.g.
   "Yes"); if it maps to none, reject.
3. For a text/number control, require a non-empty answer; keep it short and do not
   let a derived value overwrite a human-confirmed `answers.json` entry.
4. Bound the derivation to values the cited entries entail (e.g. positive years of
   experience ⇒ "Yes" for an experience question); reject a derive whose rationale
   contradicts its cited sources.
5. On rejection, return "unknown" so Task 5 asks the human — never fill a rejected
   derive.
6. Record every accepted decision (matched/derived, answer, sources, rationale) in
   the run state and the Task 9 status line.

**Acceptance criteria**
- A derived answer with no existing cited source is never filled.
- A derived choice answer that matches no option is rejected and goes to Task 5.
- "Experience on AI? [Yes/No]" is answered **Yes** from the AI years-of-experience
  entry (positive years ⇒ Yes) and the source is recorded.
- A question the store does not cover is still deferred to Task 5.
- Human-confirmed `answers.json` entries are never overwritten by a derived answer.

**Notes**
- Validation is the guard that keeps the "never invent" promise: the model may
  *derive*, but only from entries it can point to.
- Keep the validator pure and unit-testable (it takes the decision, store, options).

## Subtask 10.3 — Remember derived answers so the same question is instant next time

**Status:** 

**Goal:** Cache a derived answer so the identical question on a later run is answered
without another LLM call, while keeping `answers.json` reserved for answers the human
confirmed.

**Inputs**
- The validated derived decision (question, answer, source keys, rationale).
- A derived-answer cache (proposed `data/derived_answers.json`) and its loader.

**Steps**
1. After a derive is accepted, store `question → {answer, source_keys, rationale}`
   in the derived-answer cache (a separate file from `answers.json`).
2. On a later run, consult the cache before calling the model; reuse the cached
   answer when its cited `source_keys` still exist in `answers.json` **and** the
   stored values still support it. If a source changed or disappeared, re-derive.
3. Never write derived answers into `answers.json` (Task 5 owns that store, and only
   a human answer goes there). Never write the same key twice.
4. Load/save best-effort: a missing/corrupt cache is an empty cache, and a write
   failure never fails the run.

**Acceptance criteria**
- A derived answer is reused on a later run without a new LLM call.
- A cache entry is discarded/re-derived when its `source_keys` no longer exist or no
  longer support the answer.
- `answers.json` is never modified by a derived answer.
- A missing or corrupt cache file is handled as empty (no error).

**Notes**
- **Approved** files: `src/tools/derived_answers.py`, plus
  `data/derived_answers.json` (gitignored with the rest of `data/`).
- Keeping the cache separate preserves the "`answers.json` = human-confirmed"
  contract and makes the derivation reversible/auditable.

## Main flow — Use the reasoning chooser in the fill path


**Goal:** Wire Subtasks 10.1-10.3 into the existing fill path so Task 4/5 answer
similar questions from the store end to end.

**Steps**
1. In `src/tools/linkedin_easy_apply_fill/form_walk.py`, build the reasoning chooser
   (`build_reasoning_answer_chooser`) instead of the select-only chooser when a model
   is configured, keeping the select-only chooser as the fallback when not.
2. `_decide` in `field_filling.py` calls the chooser as today; update its Task 9
   status lines to state the source when an answer is derived vs matched.
3. Keep Task 5 as the fallback: a decision that is not grounded/validated leaves the
   question unknown and the existing ask-the-human flow runs unchanged.
4. Record each accepted decision (matched/derived, answer, sources, rationale) in the
   run state/log; do not submit.

**Acceptance criteria**
- Running the fill path, a form question the store can support is answered without
  prompting the human (verified live in the browser).
- A question the store cannot support still pauses for the human (Task 5) and is
  saved to `answers.json`.
- Task 9's panel shows the `LLM:` line with the stored source for derived answers.
- The application is **not** submitted.

**Notes**
- **Interrelated updates required (keep the codebase consistent):**
  - `README.md` — Task 4.1 bullet ("chooses the appropriate answer … by meaning") and
    Task 5 bullet, so they describe matching *and* grounding/deriving from the store.
  - Task 4.1 and Task 5 task notes that describe "select-only" / "matches by meaning",
    with human approval, since this task intentionally extends them.
  - Task 9 status text, so a derived answer names its source.
  - Tests: existing `tests/unit/test_llm_answers.py` plus new unit tests for the
    reasoning chooser and the validator.
- **Bug log:** the reported case ("Experience on AI?" reported unknown despite the
  store already covering it) is a bug — logged as **BUG-034** in
  `known Bugs/task_4_bugs.md` (Task 4 area: the answer chooser) with the symptom,
  root cause, fix, status, and evidence, and a row in `known Bugs/bug_log.md`, as
  required by AGENTS.md.
- **Live verification required:** after implementing, run the real LinkedIn flow and
  confirm in the browser that the similar question is answered from the store (and
  that a genuinely unknown question still prompts) — do not mark the task done from
  unit tests alone.
