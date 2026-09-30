---
description: AutoJobApply project rules and workflow
mode: all
---

# autojobapply — AutoJobApply

Project configuration for AI agents working in this repository. Full schema in
`SPEC.md` (approved). Sequencing in `tasks/plan.md`. Task definitions in
`tasks/todo.md`.

## The board rule (non-negotiable)

`tasks/board.md` is the **single source of truth for task status**.

- Move a card to **In Progress** *before* starting a task; move it to **Done**
  *immediately* after finishing it. Blocked work goes to **Blocked** with the blocker
  written inline.
- Never record status anywhere else. `plan.md` and `todo.md` describe *what* a task is;
  the board records *where* it is.
- WIP limit is **1** In Progress card unless the human says otherwise.
- Append a line to the board's Change Log for every move.
- A task is Done only when its acceptance criteria in `tasks/todo.md` are met and its
  verification step has actually been run — not when the code merely looks right.

## Stack

Python 3.11+ · LangGraph · browser-use (AI agent, dedicated profile) · OpenRouter via
`langchain-openai` · Pydantic v2 · SQLite (`sqlite3`) · `rich` · Poetry · ruff · mypy.

## Commands

```
poetry install
poetry run browser-use install
poetry run python -m src.main login
poetry run python -m src.main run --dry-run
poetry run python -m src.main search
poetry run python -m src.main status
poetry run pytest -m "not integration"
poetry run pytest -m integration
poetry run ruff check . --fix
poetry run mypy src
```

## Global rules

1. Nodes are thin and testable; **all I/O lives in `tools/`** (browser, DB, HTTP, PDFs).
2. **Never submit without the review gate.** No code path may bypass it.
3. **Route every network/browser action through `guard`.** Never disable or skip it.
4. Every answer carries a `Provenance` value; unknown required fields are
   `NEEDS_REVIEW`, never silently guessed.
5. Browser-use tasks are built as pure functions in `src/tools/browser_agent.py` and
   `src/nodes/fill.py` — never inline in logic; there are no DOM selectors.
6. The template placeholders (`nodes/ingest|plan|execute|verify.py`,
   `tools/opencode_client.py`, `tools/git_snapshot.py`, `workspace/`) are docstring-only
   stubs by owner decision. Do not give them invented behavior.
7. Real LinkedIn submissions only happen with explicit human approval, deliberately
   slowly (5–10/day for the first week).
8. Run `ruff check .` and `pytest -m "not integration"` before declaring anything done.
9. Ask before: adding a dependency, changing the DB schema, changing guard limits, or
   adding any submit path.
10. Never commit `.env`, cookies, the browser profile, or resumes containing PII.
