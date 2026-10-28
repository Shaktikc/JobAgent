# Task 14 — Route LLM work per purpose: MiMo-V2.6-Pro for general tasks, DeepSeek V4.1 Flash 1017 for self-healing

**Status:** ⬜ Not started

**Goal:** Give the agent **two independently configured models** instead of one
shared model:

| Purpose | Model | OpenRouter model id |
| --- | --- | --- |
| Self-healing repair agent (Task 11) | **DeepSeek V4.1 Flash 1017** | `deepseek/deepseek-v4.1-flash-1017` |
| Everything else — job/resume reading, resume descriptions, best-resume selection, form answers, job-context answers | **MiMo-V2.6-Pro** | `xiaomi/mimo-v2.6-pro` |

Every LLM path that is **not** part of self-healing must use MiMo-V2.6-Pro, and
the self-healing repair agent must use DeepSeek V4.1 Flash 1017 even when the
general model is MiMo. Changing one purpose's model must not silently change the
other. The application is **never** submitted by this task.

## Preconditions
- Tasks 3, 4.1, 10, 11, and 12 are implemented:
  - `src/tools/resume_descriptions/client.py` describes resumes and picks the
    best match (Task 3.2);
  - `src/tools/llm_answers.py` answers form questions (Task 4.1);
  - `src/tools/llm_answer_reasoning.py` matches/derives stored answers (Task 10);
  - `src/tools/job_context_answers/chooser.py` answers job-specific questions
    (Task 12);
  - `src/tools/self_healing/` and `scripts/self_heal_repair.py` implement the
    self-healing repair hook (Task 11).
- `OPENROUTER_API_KEY` is valid for **both** models, and the OpenCode CLI used by
  the repair hook is authenticated for the `openrouter` provider.
- The model ids were verified against the provider catalog:
  `xiaomi/mimo-v2.6-pro` (**MiMo-V2.6-Pro**) and
  `deepseek/deepseek-v4.1-flash-1017` (**DeepSeek V4.1 Flash 1017**).
- The model env vars may be overridden without editing code, and an unconfigured
  **general** model still falls back to Task 5 (ask the human) as today.

## Inputs
- `.env` / process environment:
  - `OPENROUTER_API_KEY` (shared credential);
  - `AUTOJOB_LLM_BASE_URL` (default `https://openrouter.ai/api/v1`);
  - `AUTOJOB_LLM_MODEL` — the **general-purpose** model; recommended
    `xiaomi/mimo-v2.6-pro`;
  - `AUTOJOB_SELF_HEAL_REPAIR_MODEL` — the **self-healing** model; default
    `deepseek/deepseek-v4.1-flash-1017`.
- `Settings.llm` (`LLMSettings`) used by all non-healing call sites.
- `Settings.self_healing` (`SelfHealingSettings`) used by the repair hook.
- `scripts/self_heal_repair.resolve_model()` and
  `src.tools.self_healing.recovery.run_repair_and_test()`.
- Existing tests: `tests/unit/test_configuration.py`,
  `tests/unit/test_self_heal_repair.py`, `tests/unit/test_self_healing.py`,
  `tests/unit/test_resume_descriptions.py`, `tests/unit/test_llm_answers.py`,
  `tests/unit/test_llm_answer_reasoning.py`,
  `tests/unit/test_task12_job_context.py`.

## Steps
1. **Add the two model settings without creating a shared fallback.**
   - Keep `AUTOJOB_LLM_MODEL` as the general model consumed by
     `LLMSettings.model`. It stays optional: with no key/model, the existing
     "LLM not configured → Task 5" behavior is unchanged.
   - Add `SelfHealingSettings.repair_model`, read from
     `AUTOJOB_SELF_HEAL_REPAIR_MODEL`, defaulting to
     `deepseek/deepseek-v4.1-flash-1017`.
   - Seal the boundary: no code path may derive the self-healing model from
     `AUTOJOB_LLM_MODEL`, and no non-healing call site may read
     `AUTOJOB_SELF_HEAL_REPAIR_MODEL`.
   - Strip surrounding whitespace/quotes and reject a blank self-healing value by
     falling back to the DeepSeek default, not to the general model.
2. **Wire the general model (MiMo-V2.6-Pro).**
   - Verify every non-healing LLM call uses `settings.llm.model`:
     `resume_descriptions/client.py` (`describe_resume`, `pick_best_resume`),
     `llm_answers.py`, `llm_answer_reasoning.py`, and
     `job_context_answers/chooser.py`. Do not pass a self-healing model into
     these calls.
   - Update the "LLM is not configured" messages to keep naming
     `AUTOJOB_LLM_MODEL`; the variable keeps its current name for backward
     compatibility, but its documented meaning becomes "general-purpose model".
   - Set `AUTOJOB_LLM_MODEL=xiaomi/mimo-v2.6-pro` in `.env.example` and the local
     (gitignored) `.env` used for verification.
   - The job-description reader itself is deterministic DOM/text extraction and
     stays model-free. Any future LLM call that reads, summarizes, or compares the
     job description belongs to this general-purpose path and must use MiMo.
3. **Wire the self-healing model (DeepSeek V4.1 Flash 1017).**
   - In `scripts/self_heal_repair.py`, add
     `DEFAULT_REPAIR_MODEL = "deepseek/deepseek-v4.1-flash-1017"` and change
     `resolve_model()` to use this order:
     1. explicit `AUTOJOB_SELF_HEAL_REPAIR_MODEL` (used verbatim, so another
        provider can be selected);
     2. otherwise the DeepSeek default.
     It must **never** fall back to `AUTOJOB_LLM_MODEL`.
   - Keep the OpenCode CLI format mapping: a bare OpenRouter id becomes
     `openrouter/deepseek/deepseek-v4.1-flash-1017`; an already qualified
     `openrouter/...` id is preserved.
   - In `src/tools/self_healing/recovery.py`, inject
     `AUTOJOB_SELF_HEAL_REPAIR_MODEL=<settings.self_healing.repair_model>` into
     the repair command environment (alongside `AUTOJOB_FAILURE_BUNDLE`,
     `AUTOJOB_BUG_ID`, etc.) so the configured self-healing model wins for the
     spawned OpenCode session.
   - Make the repair log print the resolved self-healing model explicitly, in
     addition to the existing command line.
   - Log the resolved **general** and **self-healing** models once at startup so
     each run's routing is auditable without reading code. Keep Task 9's `LLM:`
     lines unchanged; the startup log plus the repair log are the evidence.
   - On a missing/unavailable DeepSeek model, the repair must fail **closed**:
     the error stays in `repair.log`, the bug remains 🔴 Open, evidence is
     preserved, and the bounded loop stops. It must not retry with MiMo.
4. **Update documentation and defaults.**
   - `.env.example`: document both variables next to each other, with the
     purpose mapping, the exact ids, and the "no cross-fallback" rule.
   - `README.md`: setup section and the Task 11 self-healing section; replace the
     statement that the repair session reuses `AUTOJOB_LLM_MODEL` with the new
     DeepSeek default.
   - `src/configuration.py` and `scripts/self_heal_repair.py` docstrings: explain
     which purpose each model serves and the OpenRouter vs OpenCode id format.
   - Do not commit `.env` (it is gitignored); only `.env.example` changes.
5. **Update and extend the tests.**
   - `tests/unit/test_self_heal_repair.py`: replace the tests that expect
     `AUTOJOB_LLM_MODEL` to be reused. Assert:
     - with neither self-heal variable set, `resolve_model()` returns
       `openrouter/deepseek/deepseek-v4.1-flash-1017`;
     - setting only `AUTOJOB_LLM_MODEL=xiaomi/mimo-v2.6-pro` leaves that result
       unchanged;
     - an explicit `AUTOJOB_SELF_HEAL_REPAIR_MODEL` wins and is used verbatim;
     - an already `openrouter/...` id stays unchanged;
     - `main()` passes the DeepSeek id to `opencode run --model ...`.
   - `tests/unit/test_configuration.py`: assert the default
     `self_healing.repair_model`, an env override, whitespace/blank handling, and
     that `llm.model` and `self_healing.repair_model` vary independently.
   - `tests/unit/test_self_healing.py`: assert `run_repair_and_test()` passes the
     configured repair model to the repair command environment.
   - General call-site tests (`test_resume_descriptions.py`,
     `test_llm_answers.py`, `test_llm_answer_reasoning.py`,
     `test_task12_job_context.py`): assert the request model is
     `settings.llm.model` even when `AUTOJOB_SELF_HEAL_REPAIR_MODEL` is set.
   - Add the routing regression to the self-heal wrapper tests so a future change
     cannot silently reintroduce the shared-model fallback.
6. **Run the tests.**
   - Focused first:
     `uv run pytest tests/unit/test_self_heal_repair.py tests/unit/test_configuration.py tests/unit/test_self_healing.py -q`.
   - Then the full suite: `uv run pytest -q`.
   - Fix regressions before any live run. A failing repair-model test must not be
     "solved" by restoring the old shared fallback.
7. **Verify in a live run (required).**
   - Resume path: run the live resume-selection check (for example
     `AUTOJOB_RESUME_LIVE=1 uv run pytest tests/integration/test_resume_selection.py -s`)
     with the general model set to MiMo; confirm from the startup log and the
     provider request that the model is `xiaomi/mimo-v2.6-pro`.
   - Form path: run one real Easy Apply fill with a question that reaches the
     answer chooser and confirm the request model is MiMo; never click **Submit
     application**.
   - Self-heal path: run the repair wrapper against a controlled evidence bundle
     with a recording/stub `opencode` (or a real `opencode run --model ...` smoke
     call) and confirm the argv model is
     `openrouter/deepseek/deepseek-v4.1-flash-1017` while MiMo remains the general
     model. If a real self-heal retry is feasible, confirm the resumed session uses
     the same job and the DeepSeek model; otherwise preserve the command/argv
     evidence in the bundle.
   - Confirm no submit click, no stale browser session, and no profile lock after
     the checks.
8. **Record the outcome.** If implementation exposes a new bug, add
   `known Bugs/task_14_bugs.md` (ask the human before creating the file) and the
   matching row in `known Bugs/bug_log.md`, with symptom, root cause, fix, status,
   and evidence. Mark this task ✅ Done only after the user reviews and approves
   the completed work; update `task/task.md` at the same time.

## Acceptance criteria
- `AUTOJOB_LLM_MODEL` is documented and set to **MiMo-V2.6-Pro**
  (`xiaomi/mimo-v2.6-pro`) for every non-healing LLM path.
- The self-healing repair agent defaults to **DeepSeek V4.1 Flash 1017**
  (`deepseek/deepseek-v4.1-flash-1017`; OpenCode id
  `openrouter/deepseek/deepseek-v4.1-flash-1017`) via
  `AUTOJOB_SELF_HEAL_REPAIR_MODEL`.
- `resolve_model()` ignores `AUTOJOB_LLM_MODEL`; an explicit
  `AUTOJOB_SELF_HEAL_REPAIR_MODEL` still wins. There is no cross-purpose
  fallback in either direction.
- `run_repair_and_test()` hands the configured repair model to the spawned repair
  command, and the repair log shows it.
- The startup log names both resolved models, so routing is auditable in every
  run.
- Every non-healing call site (resume description, best-resume matching, Task
  4.1, Task 10, Task 12) sends MiMo-V2.6-Pro, even when the self-healing model is
  also configured.
- Unit tests and the relevant live checks pass (a real resume-selection LLM call
  and a real browser fill); the live checks prove both model ids are actually
  used.
- A failed self-healing model call fails closed: evidence and the 🔴 Open bug
  entry are preserved, the loop stops at its attempt cap, and it never silently
  falls back to MiMo.
- The agent never clicks **Submit application**.

## Notes
- **Id formats are different on purpose.** The Python app talks to the
  OpenRouter API and uses `xiaomi/mimo-v2.6-pro` /
  `deepseek/deepseek-v4.1-flash-1017`. The OpenCode CLI needs the provider
  prefix: `openrouter/xiaomi/mimo-v2.6-pro` /
  `openrouter/deepseek/deepseek-v4.1-flash-1017`. The wrapper normalizes bare
  ids; do not store the `openrouter/` prefix in the general Python setting.
- **OpenCode credentials are separate.** The repair subprocess inherits
  `OPENROUTER_API_KEY`, but the OpenCode `openrouter` provider must also be
  authenticated in the environment where the self-heal loop runs. Verify a
  trivial `opencode run --model openrouter/deepseek/deepseek-v4.1-flash-1017`
  call before relying on the repair hook.
- **Cost/quality split:** MiMo-V2.6-Pro handles reading/comprehension-heavy work
  (job and resume understanding, matching, prose answers). DeepSeek V4.1 Flash
  1017 handles the self-healing repair session, which reasons over code, evidence,
  and tests.
- **Reasoning:** the structured Task 3.2 calls keep
  `AUTOJOB_LLM_DISABLE_REASONING=true` for MiMo's JSON replies. If MiMo returns
  an unusable/empty reply with reasoning disabled, fix the request rather than
  switching the general model to DeepSeek.
- **Fail loudly, do not guess.** If a configured model id is rejected by the
  provider, surface the provider error; never silently substitute the other
  model or an unset model.
- **Proposed new module (needs human approval before creating):** if the routing
  constants/helpers do not fit cleanly in `src/configuration.py`, put them in a
  new `src/tools/llm_model_routing.py` with the default ids and OpenCode-id
  normalization, and re-export nothing unrelated. Ask for approval of the file
  name before creating it, and keep it under the 415-line limit.
- **Interrelated updates:** configuration parsing, the repair wrapper, recovery
  env injection, `.env.example`, README, docstrings, and every affected unit/
  integration test must change together. Do not leave a caller or test assuming
  the old shared `AUTOJOB_LLM_MODEL` behavior.
- **Task-file rule:** do not edit `task/` files during implementation except to
  mark this task done and update `task/task.md` after human review.
- Never click **Submit application**; submission remains a manual human step.
