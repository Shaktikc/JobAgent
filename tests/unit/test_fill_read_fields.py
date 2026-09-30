"""Unit tests for the Easy Apply field-read seam (Tasks 7/8/17, CP-B).

The fields on an Easy Apply form are **dynamic** — every job asks its own questions,
so these tests never assume a fixed field list. They pin behavior that must hold for
*whatever* labels the live agent reports:

- **Read fidelity:** every non-blank label the agent saw is returned to the caller,
  so it can be answered (this is what failed in the 2026-09-30 real dry-run of job
  ``4468706364``: labels were dropped and the answers were recorded ``NEEDS_REVIEW``).
- **A failed read is not an empty form:** ``open_and_read_fields`` must raise
  ``FillError`` when the agent returns no usable ``FormFields`` / reports failure —
  never silently return ``()``, which turns every dynamic field into ``NEEDS_REVIEW``
  with no signal anything went wrong.
- **A failed read marks the job ``failed``** in the store (the ``_node_answer`` seam).

The agent is stubbed at the ``browser_agent.run_task`` boundary, so these are pure
with respect to the network and LLM and exercise the real read/answer/store code.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.configuration import AppSettings, FactsConfig
from src.graph import Runtime, _node_answer
from src.nodes import answer as answering
from src.nodes import fill
from src.nodes.fill import FormFields
from src.tools import store
from src.tools.browser_agent import AgentRunResult

FACTS_PATH = Path(__file__).resolve().parents[2] / "config" / "facts.yaml"

# Representative labels only — a stand-in for whatever the agent reports on a live
# form. No assertion depends on these being the real fields of any particular job.
SOME_LABELS = ("Email address*", "Years of experience*", "Are you legally authorized to work?")


class _Agent:
    """A stub ``browser_agent.run_task`` returning a canned ``AgentRunResult``."""

    def __init__(self, result: AgentRunResult) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> AgentRunResult:
        self.calls += 1
        return self.result


def _read(monkeypatch: pytest.MonkeyPatch, result: AgentRunResult) -> tuple[str, ...]:
    agent = _Agent(result)
    monkeypatch.setattr(fill.browser_agent, "run_task", agent)
    return asyncio.run(fill.open_and_read_fields(browser=object(), llm=object(), guard=None))


# --- the read must surface the labels it saw --------------------------------


def test_read_returns_every_label_the_agent_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = AgentRunResult(
        done=True,
        successful=True,
        structured_output=FormFields(fields=list(SOME_LABELS)),
    )

    labels = _read(monkeypatch, result)

    assert labels == SOME_LABELS


def test_read_returns_whatever_labels_appear_not_a_fixed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read is a faithful pass-through: any label set the agent reports survives.

    Forms are dynamic; the contract is "whatever you saw, I keep", not a schema of
    expected fields.
    """
    arbitrary = ("Cover letter", "Expected salary (AUD)", "Notice period", "GitHub URL")
    result = AgentRunResult(
        done=True,
        successful=True,
        structured_output=FormFields(fields=list(arbitrary)),
    )

    labels = _read(monkeypatch, result)

    assert labels == arbitrary


def test_read_drops_blank_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    result = AgentRunResult(
        done=True,
        successful=True,
        structured_output=FormFields(fields=["Email address*", "  ", "Mobile phone number*"]),
    )

    labels = _read(monkeypatch, result)

    assert labels == ("Email address*", "Mobile phone number*")


# --- Bug 3: a failed read must not look like "no fields" --------------------


def test_read_with_no_structured_output_is_not_silently_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read that produced no ``FormFields`` is a failure, not an empty form.

    ``discover.read_job`` raises ``DiscoveryError`` when its extraction is missing;
    the fill read must be equally explicit. Returning ``()`` here is what turned a
    broken field-read into a run where every answer silently became NEEDS_REVIEW.
    """
    result = AgentRunResult(done=True, successful=True, structured_output=None)

    with pytest.raises(fill.FillError):
        _read(monkeypatch, result)


def test_read_with_unstructured_output_is_not_silently_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dict/raw payload is not a ``FormFields``; that is a schema failure to surface."""
    result = AgentRunResult(
        done=True,
        successful=True,
        structured_output={"fields": list(SOME_LABELS)},
    )

    with pytest.raises(fill.FillError):
        _read(monkeypatch, result)


def test_read_surfaces_an_unsuccessful_agent_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the agent reports failure, a partial/empty read must not be trusted."""
    result = AgentRunResult(done=True, successful=False, structured_output=None)

    with pytest.raises(fill.FillError):
        _read(monkeypatch, result)


# --- Bug 2: labels that reach the rules get an answer, never silently dropped ---


def test_every_read_label_gets_exactly_one_answer_not_silently_dropped() -> None:
    """The answer step is a faithful pass-through for *any* dynamic field set.

    Whatever labels the read produced must each yield exactly one ``Answer`` — a
    value when a rule covers it, ``NEEDS_REVIEW`` when nothing does. The 2026-09-30
    bug was labels vanishing between read and answer; the guarantee is structural
    (one answer per label), not tied to any particular job's fields.
    """
    config = FactsConfig.from_yaml(FACTS_PATH)  # real rules; fields stay arbitrary
    arbitrary = (
        "Email address*",
        "Favorite color*",
        "How many years of Python?",
        "Do you require sponsorship?",
    )

    answers = answering.answer_fields(list(arbitrary), config)

    assert [a.field for a in answers] == list(arbitrary)
    assert all(a.field in arbitrary for a in answers)
    # No field is silently absent; each is answered or explicitly NEEDS_REVIEW.
    assert all(a.value or a.provenance.value == "NEEDS_REVIEW" for a in answers)


# --- the answer node must mark a failed read as `failed`, like fill does -----


def _runtime_with_job(conn: Any) -> Any:
    """A minimal ``Runtime`` whose discover row is already persisted."""
    store.upsert_job(
        conn,
        store.Job(job_id="job-123", title="Some Role", company="Some Co"),
    )
    return Runtime(
        settings=AppSettings(),
        conn=conn,
        browser=object(),
        llm=object(),
        guard=None,
        facts=FactsConfig(facts={}, rules=[]),
        resume_path=None,
        dry_run=True,
        job_url="https://example.test/jobs/job-123",
    )


def test_answer_node_marks_job_failed_when_field_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed field-read must mark the job ``failed``, exactly like ``_node_fill``.

    Before the fix, ``open_and_read_fields`` returned ``()`` on a bad read and
    ``_node_answer`` never touched the store — so a broken read left the job ``seen``
    and every answer NEEDS_REVIEW with no failure signal. When the read now raises
    ``FillError``, the node must persist ``failed`` before propagating.
    """
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store.init_db(conn)
    runtime = _runtime_with_job(conn)

    agent = _Agent(AgentRunResult(done=True, successful=True, structured_output=None))
    monkeypatch.setattr(fill.browser_agent, "run_task", agent)

    with pytest.raises(fill.FillError):
        asyncio.run(_node_answer(runtime, {"job": {"job_id": "job-123"}}))

    assert store.get_job(conn, "job-123").status is store.JobStatus.FAILED