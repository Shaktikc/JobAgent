# Task 23 — Independent resume and stored-answer LLM models

| ID | Symptom | Status | Fix commit(s) |
|----|---------|--------|---------------|
| BUG-112 | Visible CSS asterisks were lost, so required questions never reached Task 10 | 🟢 Fixed | Uncommitted; base `b560bb6` |

### BUG-112 — CSS-generated required markers were missing from question labels

- **Symptom:** During Task 23's real LinkedIn check on job `4485109057`, the
  resume request used the intended Task 3 model, but all six visibly starred
  Additional Questions were classified as optional. No Task 10 request or Task 5
  prompt ran, and Review did not advance. The same issue affected contact labels
  on job `4483888327`.
- **Root cause:** LinkedIn's classic labels render their asterisks using CSS
  `::after { content: "*"; }`. The shared Task 21 question-label reader inspected
  DOM text only. The required-only filter then correctly rejected the incomplete
  labels, which contained no asterisks.
- **Fix:** Include visible text asterisks from each question label's rendered
  `::before`/`::after` pseudo-elements and its label descendants. Ignore hidden,
  invisible, and transparent pseudo-elements. Do not infer requiredness from
  metadata or borrow markers from adjacent questions or trailing helper text.
- **Status:** 🟢 Fixed — browser regressions and the real LinkedIn model-routing
  check pass. Task 23 itself still awaits user verification.
- **Evidence:** `src/tools/linkedin_easy_apply_fill/question_labels.py`;
  `tests/integration/test_task23_generated_required_markers_live.py` failed
  before the fix (`0` required controls instead of `5`). The regression covers
  inputs, textareas, selects, radio groups, descendant markers, hidden markers,
  text inside `display: contents` spans, and unchanged optional values. Initial
  real-site evidence is preserved under
  `data/debug/task23/20261103T062022Z/` and
  `data/debug/task23/20261103T062500Z/` (screenshots, labels, markup, and request
  model IDs). Direct browser inspection confirmed `::after` content `"*"`,
  display `inline`, and visibility `visible` on the affected labels.
  After the fix, all 14 generated-marker and existing Task 21 label browser
  regressions passed. Real-site evidence:
  `data/debug/task23/20261103T063601Z/verification.json`. Task 3 sent
  `xiaomi/mimo-v2.6-pro` (HTTP 200); Task 10 sent
  `deepseek/deepseek-v4.1-flash-1017` (seven HTTP 200 responses), filled five
  grounded store answers, and passed one unsupported question to the real Task 5
  prompt. No application was submitted; the existing validation flow closed the
  application after the unanswered required question timed out.
  Final checks: 794 passed / 94 opt-in tests skipped in the default suite;
  14 browser regressions passed separately; full Ruff checks and wheel build
  passed. Reports: `data/debug/task23/pytest.xml` and
  `data/debug/task23/browser-regressions.xml`.
  Commit: uncommitted working-tree fix; base `b560bb6` (no commit authorized).
