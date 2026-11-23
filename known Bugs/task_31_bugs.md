# Task 31 bugs

## T31-001 — Stored answers missed before the human prompt

- **Symptom** A required question could open the banner even when the answer store held a usable answer.
- **Root cause** Normal fill and recovery used the first chooser result without independently checking the store before prompting.
- **Fix** Both paths now use one bounded second look. Exact matches return immediately. The configured answer model can re-read the store once when needed.
- **Status** 🟢 Fixed
- **Evidence** `src/tools/answer_second_look.py`, `src/tools/linkedin_validation/required_answers.py`, and `tests/unit/test_task31_answer_second_look.py`. The LinkedIn JavaScript experience question filled after a forced miss with zero banners. Commit pending.

## T31-002 — A single unchecked answer could still prompt

- **Symptom** A grounded negative answer to a single checkbox could reach the banner before the form accepted the unchecked state.
- **Root cause** The checkbox prompt and recovery guards treated an empty list of selected options as an unknown answer.
- **Fix** Normal fill and recovery recognize an explicit negative answer to a single checkbox.
- **Status** 🟢 Fixed
- **Evidence** `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`, `src/tools/linkedin_validation/required_controls.py`, and `tests/unit/test_task31_answer_second_look.py`. Commit pending.

## T31-003 — Live verification clicked Done before it was enabled

- **Symptom** The first live fallback check timed out after the harness entered an answer.
- **Root cause** A fixed delay allowed the harness to click Done before the form watcher enabled it.
- **Fix** The harness now waits for the enabled button under a deadline and checks that the temporary store is still empty before clicking.
- **Status** 🟢 Fixed
- **Evidence** `scripts/verify_task31_linkedin.py` passed on the Zone IT Solutions JavaScript question. The unsupported-store case recorded one completed banner and saved the answer after Done. Commit pending.
