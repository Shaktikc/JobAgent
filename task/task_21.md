# Task 21 — Skip every Easy Apply question without an asterisk

**Status:** ✅ Done

**Goal:** Skip every Easy Apply question without a visible `*` on its own label
or group heading, regardless of topic, control type, or form step. Leave it
untouched and continue without asking the human. This rule does not depend on
voluntary helper text or on the question belonging to any particular category.

**Reported example**
- Screenshot: `C:/Users/shakt/OneDrive/Pictures/Screenshots 1/Screenshot 2026-11-02 163014.png`.
- LinkedIn Easy Apply: **Apply to TikTok**, **Additional Questions**, page 3/4.
- Question: **What term best describes your gender identity?**
- The question has no `*`; its helper text explicitly says it is voluntary and
  will not affect the job application. The demographic survey also says answering
  is completely voluntary. Despite this, the agent displayed an unknown-answer
  prompt asking the human to answer it.
- The same screenshot shows an unstarred, voluntary disability question below
  it; the fix must cover optional questions generally, not just one wording.

**Expected behavior**
1. Discover each current step's question labels, group headings, and controls
   dynamically. Resolve requiredness per question/group, without inheriting a
   `*` or required flag from another question, option, section, or ancestor.
2. Skip every question with no visible `*` on its own question/group label. Review
   `required`/`aria-required` metadata and the existing group-level requiredness
   logic so a metadata-only flag cannot override the no-asterisk skip rule.
   Apply the rule even when there is no optional/voluntary helper text.
3. Filter optional questions before LLM answer selection, stored-answer lookup,
   checkbox/radio-group filling, and the human-question banner. Do not ask even
   when the answer is unknown, and do not fill even when an answer is remembered.
4. Leave every unstarred field or group unchanged, including existing values
   and selections. Do not choose a default option, infer an answer from other
   sources, or auto-fill it from a remembered answer.
5. Do not count skipped optional questions as unknown or unfilled required
   fields, wait for an answer, or trigger a retry/self-healing loop solely
   because they are blank. Continue with required fields and normal navigation.
   Genuine visible validation errors retain Task 20's existing handling.
6. Preserve normal filling and human assistance for questions with their own
   visible `*`. Never click **Submit application**.

**Acceptance criteria and verification**
- Every unstarred question remains untouched and produces no human banner,
  LLM answer request, stored-answer write, or wait for an answer. The reported
  screenshot is one regression example of this universal rule.
- Text inputs, textareas, selects, radio groups, checkbox groups, and other
  question controls follow the same policy on every step, for any topic and
  whether or not optional/voluntary helper text is present. An unstarred
  question beside a starred required question stays optional.
- The form advances past steps containing only unstarred questions without answering them;
  starred required questions still use their existing fill/ask flow.
- Regression tests cover classic and SDUI markup, group-label discovery,
  misleading/inherited required flags, nearby asterisks, presence/absence of helper text,
  known and unknown answers, and preserving existing optional selections.
- Live-browser verification on LinkedIn confirms unstarred questions are skipped
  and navigation continues without submitting an application. Unit tests alone
  do not complete this task.

**Implementation notes**
- Creation only is authorized now; implementation and verification are pending.
- Required-only filtering already exists. Diagnose why the reported group
  bypassed it from the live DOM; do not assume the root cause from the screenshot
  or hardcode any question text, topic, control type, or step number.
- Review `src/tools/forms.py`,
  `src/tools/linkedin_easy_apply_fill/required_only.py`,
  `src/tools/linkedin_easy_apply_fill/form_queries/`,
  `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`, the field-filling and
  form-walk modules, human-question handling, related tests, and documentation.
- Log bugs fixed during implementation under `known Bugs/task_21_bugs.md` and
  update `known Bugs/bug_log.md`; respect the 415-line source-file limit.
- Mark Task 21 in progress only when implementation starts, and done in this
  file and the index only after implementation and live verification.
