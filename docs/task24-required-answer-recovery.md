# Required-answer recovery (Task 24)

The fill walker detects visible validation before navigation and after each
Next/Review attempt. Detection includes “This field is required”, required/entry
messages, invalid controls and group-level feedback. Association follows the
live question's controls; another question's feedback cannot require an answer.
Task 21 still applies: only the question's own visible `*` allows answering.

Recovery keeps committed form answers, then uses the existing Task 10/12 chooser,
then Task 5's banner. It never supplies a default answer. The same attempt tracker
covers initial filling and recovery, preventing a second chooser call or prompt
after the human skips. Each recovery pass handles at most five questions and
uses one Next/Review retry. It never clicks Submit.

The real control is re-discovered after answer resolution and after each choice
action. Text/select values and the whole radio/checkbox selection are verified
before navigation. Errors in detection, resolution, prompting or navigation
become validation outcomes, bypassing structural self-healing.

Task 5 owns completion and persistence for both normal filling and recovery.
Text requires blur, Enter or Done; multi-checkbox groups require Done. A skipped
or timed-out partial answer is neither saved nor returned. User activity extends
the inactivity deadline. The recovery adds no separate wait or save loop.
`AUTOJOB_SESSION_ASK_HUMAN=false` never waits for a human.

Unresolved answers use Task 20's durable `data/invalid_input_skips.json` journal
before closing/discarding the form. Records include the canonical job link,
question, visible redacted message, automatic/human attempt flags and failure
reason. Successful recovery adds no skip. A failed write or close stops safely
and preserves the link. Existing graph accounting continues to the next eligible
posting only after both logging and closing succeed.

Implementation: `linkedin_validation/required_answers.py` owns bounded answer
resolution, `required_controls.py` owns live grouping/application checks, and
`linkedin_easy_apply_fill/form_walk/` separates orchestration from rendering
readiness. Public walker imports remain available; monkeypatches target `core`.

Verification uses `scripts.verify_task24_linkedin` in the dedicated browser:

```powershell
.venv/Scripts/python.exe -m scripts.verify_task24_linkedin --launch --hold
# Attach using the printed CDP address and inspect the current form.
.venv/Scripts/python.exe -m scripts.verify_task24_linkedin --cdp-url http://127.0.0.1:PORT
# On a real rejected step, use production recovery. No submission occurs.
.venv/Scripts/python.exe -m scripts.verify_task24_linkedin --cdp-url http://127.0.0.1:PORT --recover automatic
# Or show the actual banner, or verify the disabled-human safe skip.
# --recover human / --recover disabled
```

The verification script also supports a bounded walk to a question discovered in
the form (`--until-question`), filling grounded answers while leaving that
question blank (`--prepare --leave-question`), and a single Next/Review click
(`--next`). These options reproduce a real missing-answer validation state.
