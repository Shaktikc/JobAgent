# Task 12 bugs

## T12-001 - Lost reason for a job-context handoff

- **Symptom** The CORTO skip record shows an automatic attempt and a human prompt for "Why are you interested in this role?" but gives only the human skip reason.
- **Root cause** The required-answer tracker recorded that the chooser ran and discarded its rejection rationale.
- **Fix** Save Task 12's rejection in the attempt before prompting. Keep the human outcome separately. Clarify how the model can ground a role-interest answer in a job responsibility and relevant resume experience.
- **Status** 🟢 Fixed
- **Evidence** `src/tools/linkedin_validation/required_answers.py`, `tests/unit/test_task12_handoff.py`, and `tests/integration/test_job_context_live.py`. The original model rejection cannot be recovered from the historical journal. Live CORTO review: `data/debug/task23/20261123T064038Z/verification.json`. Commit: uncommitted.
