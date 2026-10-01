# AutoJobApply — agent instructions

**`SPEC.md` (approved) is the source of truth** for requirements, architecture,
directory layout, and success criteria. Read the relevant section before changing
behavior, and cite it as `SPEC.md §N` in code comments.

## Where things live

- `SPEC.md` — full specification (source of truth)
- `tasks/plan.md` — sequencing, decisions, risks
- `tasks/todo.md` — task definitions: acceptance criteria, verification, files
- `tasks/board.md` — **single source of truth for task status**
- `docs/decisions/` — architecture decision records
- `.opencode/agents/autojobapply.md` — the named project agent (agent-specific config only; it defers to this file)

## The board rule (non-negotiable)

`tasks/board.md` is the **only** place task status is recorded.

- Move a card to **In Progress** *before* starting a task and to **Done**
  *immediately* after finishing it. Blocked work goes to **Blocked** with the
  blocker written inline.
- WIP limit is **1** In Progress card unless the human says otherwise.
- Append one line to the board's Change Log for every move.
- Never record status in `plan.md` or `todo.md`.
- A task is Done only when its `tasks/todo.md` acceptance criteria are met and
  its verification step has actually been run.

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

## Hard invariants (details in `SPEC.md` §8)

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
7. Real LinkedIn submissions only with explicit human approval, deliberately slowly
   (5–10/day for the first week).
8. Ask before: adding a dependency, changing the DB schema, changing guard limits,
   or adding any submit path.
9. Never commit `.env`, cookies, the Chromium profile, or resumes containing PII.
10. **Do not `git commit` or `git push` unless the human explicitly says to.** Leave
    changes in the working tree and wait for explicit approval before any commit or push.

Run `ruff check .` and `pytest -m "not integration"` before declaring anything done.
