"""Task 4 steps 2-3 via browser-use's LLM agent.

Task 4 (see :mod:`src.tools.linkedin_easy_apply_fill`) enumerates the open Easy
Apply form and must, for every field, decide whether the answer is already known
(Task 4 step 2) and fill the ones that are (step 3). This module makes
browser-use's LLM ``Agent`` (driven by OpenRouter) the **sole** mechanism for
those two steps, guided by the question -> answer store. Fields the agent leaves
empty are handed to Task 5, which asks the human. There is no deterministic
store fallback: with no model configured, the offline deterministic fill is used
instead of the agent.

Safety comes first:

* While the agent runs, a capture-phase click/submit guard disables every
  navigation, close, and **Submit** control inside the apply surface, so the
  agent can never advance or submit the application. Submission stays a manual
  human step (see ``AGENTS.md``).
* The agent's toolset is restricted to form interaction; navigation, tab
  management, file writing, and resume upload are excluded.
* The agent is pointed at the exact tab Task 4 is driving (the actor page's CDP
  target) rather than browser-use's default ``about:blank`` tab, so it sees the
  open form instead of an empty page.
* Any agent error or timeout is swallowed and recorded; the fields it did not
  fill are left for Task 5 rather than filled deterministically.

The heavy ``browser-use`` extra (and the OpenRouter SDK it uses) is imported
lazily, so importing this module never requires the browser extra.
"""

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from src.configuration import Settings
from src.tools.browser import _safe

# Agent actions that could step outside "fill the fields on this step" (navigate
# away, manage tabs, read/write files, upload the resume the deterministic code
# owns, or extract content). Everything else — click, input, select_dropdown,
# dropdown_options, scroll, wait, find_*, evaluate, screenshot, done — stays.
_AGENT_EXCLUDED_ACTIONS = (
    "navigate",
    "search",
    "go_back",
    "close",
    "switch",
    "read_file",
    "replace_file",
    "write_file",
    "save_as_pdf",
    "upload_file",
    "extract",
)


class AgentFillReport(BaseModel):
    """A lightweight record of one LLM agent fill attempt (for logs/outcome)."""

    ran: bool = False
    note: str = ""
    steps: int = 0


def build_agent_task(answers: dict[str, str], title: str = "") -> str:
    """Build the prompt telling the agent which known answers to fill.

    Pure so it is unit-testable: the prompt lists the known ``question -> answer``
    pairs and pins the hard rules (only fill known answers, never guess, never
    navigate or submit).
    """
    header = [
        "You are filling ONE step of a LinkedIn Easy Apply application form that is ALREADY OPEN",
        "in the current browser tab. Do not navigate away.",
    ]
    if title:
        header.append(f"This step is titled: {title!r}.")
    rules = [
        "",
        "For each visible form field, decide whether its question is already answered by the",
        "KNOWN ANSWERS below (match semantically; ignore case, punctuation, and spacing).",
        "If a field matches a known answer, fill it using the form's own control: type text into",
        "text inputs, tick the matching radio/checkbox, or choose the matching dropdown option.",
        "If a field is NOT covered by a known answer, leave it completely untouched — never guess",
        "and never invent an answer.",
        "Do NOT click Next, Continue, Review, Back, Submit, or any navigation/close button: they",
        "are disabled and must stay untouched.",
        "Do NOT upload or change the resume, open links, or open/close tabs.",
        "When every known field on this step is filled, finish.",
        "",
        "KNOWN ANSWERS (question -> answer):",
        json.dumps(answers, indent=2, ensure_ascii=False),
    ]
    return "\n".join(header + rules)


# Capture-phase guard installed while the agent drives the page. It blocks clicks
# on any button/link whose text looks like navigation, close, or submit, and
# blocks form submission outright, so the agent cannot advance or submit even if
# it tries. The handler is stashed on ``window`` so it can be removed precisely.
GUARD_NAV_JS = r"""
() => {
  const KEY = '__autojobAgentGuard';
  const existing = window[KEY];
  if (existing && existing.installed) return true;
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const isBlocked = (node) => {
    for (let i = 0; i < 5 && node && node.nodeType === 1; i++) {
      const tag = node.tagName.toLowerCase();
      const role = (node.getAttribute('role') || '').toLowerCase();
      if (tag === 'button' || tag === 'a' || role === 'button') {
        const text = norm(node.innerText) + ' ' + norm(node.getAttribute('aria-label'));
        if (/(next|continue|review|submit|apply|back|dismiss|cancel|close)/i.test(text)
            || /(save|discard|later|upload|attach|resume|choose file)/i.test(text)) {
          return true;
        }
      }
      node = node.parentElement;
    }
    return false;
  };
  const onClick = (event) => {
    if (isBlocked(event.target)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  };
  const onSubmit = (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  document.addEventListener('click', onClick, true);
  document.addEventListener('submit', onSubmit, true);
  window[KEY] = { installed: true, onClick: onClick, onSubmit: onSubmit };
  return true;
}
"""

# Remove the guard so the deterministic code can drive navigation again.
UNGUARD_NAV_JS = r"""
() => {
  const KEY = '__autojobAgentGuard';
  const guard = window[KEY];
  if (!guard || !guard.installed) return true;
  document.removeEventListener('click', guard.onClick, true);
  document.removeEventListener('submit', guard.onSubmit, true);
  delete window[KEY];
  return true;
}
"""


def build_agent_llm(settings: Settings):
    """Build the OpenRouter chat model for the agent, or ``None`` if unavailable."""
    if not settings.llm.configured:
        return None
    try:
        from browser_use import ChatOpenRouter
    except ImportError:  # pragma: no cover - depends on the optional install
        return None
    return ChatOpenRouter(
        model=settings.llm.model,
        temperature=settings.llm.temperature,
        timeout=settings.llm.timeout_seconds,
    )


def _build_agent(session, llm, task: str, settings: Settings):
    """Construct a tightly-scoped browser-use ``Agent`` for the open form step."""
    from browser_use import Agent, Tools

    tools = Tools(exclude_actions=list(_AGENT_EXCLUDED_ACTIONS))
    return Agent(
        task=task,
        llm=llm,
        browser=session,
        tools=tools,
        use_vision=False,
        max_actions_per_step=3,
        enable_planning=False,
        enable_signal_handler=False,
        directly_open_url=False,
    )


async def _focus_agent_on_page(session, page) -> None:
    """Point browser-use's agent focus at the tab this run is driving.

    Tasks 1-4 drive a browser-use actor ``Page`` by its CDP target id, which does
    **not** update ``BrowserSession.agent_focus_target_id``. Left alone, the LLM
    agent starts on the initial ``about:blank`` screensaver tab (a different
    target), sees an empty DOM, and its element-index actions all fail. Focusing
    the actor page's target makes the agent see and fill the open Easy Apply form.

    Best-effort: a session/page without CDP (e.g. the unit-test fakes) is a no-op.
    """
    target_id = getattr(page, "_target_id", None) or getattr(page, "target_id", None)
    focus = getattr(session, "get_or_create_cdp_session", None)
    if target_id and callable(focus):
        await _safe(focus(target_id, focus=True))


async def fill_known_fields_with_agent(
    page,
    session,
    answers: dict[str, str],
    settings: Settings,
    notify,
    *,
    agent_factory=None,
    llm=None,
) -> AgentFillReport | None:
    """Task 4 steps 2-3: let the LLM agent decide and fill the known fields.

    Returns ``None`` when the agent is disabled (no model/key or the feature gate
    is off), or an :class:`AgentFillReport` describing the attempt. Errors and
    timeouts are reported, never raised; fields left empty go to Task 5.
    """
    if not settings.agent_fill_enabled:
        return None
    if not answers:
        # Nothing is known on this step; skip the LLM entirely.
        return AgentFillReport(ran=False, note="no known answers on this step")
    llm = llm if llm is not None else build_agent_llm(settings)
    if llm is None:
        return None

    task = build_agent_task(answers)
    await _safe(page.evaluate(GUARD_NAV_JS))
    report = AgentFillReport(ran=True)
    try:
        factory = agent_factory or _build_agent
        agent = factory(session, llm, task, settings)
        # The agent otherwise defaults to the about:blank tab, not the open form.
        await _focus_agent_on_page(session, page)
        history = await asyncio.wait_for(
            agent.run(max_steps=settings.llm.max_steps),
            timeout=settings.llm.timeout_seconds,
        )
        report.steps = _history_steps(history)
        report.note = "agent finished"
        if not _agent_succeeded(history):
            report.note = "agent finished without confirming success"
    except TimeoutError:
        report.note = f"agent timed out after {settings.llm.timeout_seconds:g}s"
    except Exception as exc:  # noqa: BLE001 - a failure must not stop the run
        report.note = f"agent failed: {type(exc).__name__}: {exc}"
    finally:
        await _safe(page.evaluate(UNGUARD_NAV_JS))

    notify(f"Task 4: LLM agent fill attempt - {report.note}.")
    return report


def _history_steps(history) -> int:
    """Best-effort count of the agent's steps, tolerant of any history shape."""
    try:
        raw = getattr(history, "history", None)
        if raw is not None:
            return len(raw)
        number = getattr(history, "number_of_steps", None)
        return int(number) if number else 0
    except Exception:  # noqa: BLE001 - logging only
        return 0


def _agent_succeeded(history) -> bool:
    """Whether the agent's final step reported success.

    Best-effort: histories that do not expose ``is_successful`` (e.g. the test
    fakes) count as successful. ``None`` means the agent stopped before it finished
    (for example it hit the step budget), which is treated as not confirmed.
    """
    check = getattr(history, "is_successful", None)
    if not callable(check):
        return True
    try:
        return check() is True
    except Exception:  # noqa: BLE001 - logging only
        return True


__all__ = [
    "AgentFillReport",
    "GUARD_NAV_JS",
    "UNGUARD_NAV_JS",
    "build_agent_llm",
    "build_agent_task",
    "fill_known_fields_with_agent",
]
