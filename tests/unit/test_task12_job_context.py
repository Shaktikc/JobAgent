"""Task 12: per-job context, grounded answers, and routing (offline)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.configuration import LLMSettings, SelfHealingSettings, SessionSettings, Settings
from src.state import (
    ApplyState,
    FormField,
    JobAnswerContext,
    JobDescription,
    Task2Outcome,
    Task3Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools.answers import normalize_question
from src.tools.job_context import build_job_context
from src.tools.job_context_answers import (
    ContextAwareAnswerChooser,
    JobContextChooser,
    build_context_messages,
    is_free_text_field,
    looks_job_specific,
    parse_context_reply,
    validate_context_decision,
)
from src.tools.llm_answers import QuestionDecision
from src.tools.resume_descriptions import canonical_path

_QUESTION = "What attracts you to Propeller as an employer?"
_JOB = JobDescription(
    title="Senior Python Engineer",
    company="Propeller",
    location="Sydney",
    body="Propeller's mission is to make hiring fair for everyone. We build Python services.",
)
_RESUME = "Python engineer with 6 years building reliable services. I value fair hiring."
_PROFILE = {"summary": "Python engineer", "skills": ["Python"], "years_experience": 6}
_RESUME_EVIDENCE = "Python engineer with 6 years building reliable services"
_JOB_EVIDENCE = "Propeller's mission is to make hiring fair for everyone"


def _context(
    *, job: JobDescription = _JOB, resume_text: str = _RESUME, profile: dict | None = None
) -> JobAnswerContext:
    return JobAnswerContext(
        job_description=job,
        resume_path="resumes/a.txt",
        resume_text=resume_text,
        resume_profile=dict(_PROFILE if profile is None else profile),
    )


# --- Subtask 12.1: build and thread the context -----------------------------
def test_build_context_reads_resume_and_profile_without_modifying_the_file(tmp_path) -> None:
    resume = tmp_path / "a.txt"
    resume.write_text(_RESUME, encoding="utf-8")
    store = tmp_path / "descriptions.json"
    store.write_text(
        json.dumps({canonical_path(resume): _PROFILE}), encoding="utf-8"
    )

    context = build_job_context(_JOB, str(resume), store)

    assert context.resume_path == str(resume)
    assert context.resume_text == _RESUME
    assert context.resume_profile["summary"] == "Python engineer"
    assert context.sources == ["resume", "job_description"]
    assert context.audit().profile_available is True
    assert resume.read_text(encoding="utf-8") == _RESUME  # read-only


def test_build_context_caps_long_text_and_survives_a_bad_resume(tmp_path) -> None:
    long_job = _JOB.model_copy(update={"body": "x" * 500})
    missing = build_job_context(
        long_job, str(tmp_path / "absent.txt"), None, max_job_chars=100
    )
    assert missing.sources == ["job_description"]
    assert missing.errors and "resume" in missing.errors[0]
    assert missing.job_description.body.endswith("...[truncated]")

    resume = tmp_path / "a.txt"
    resume.write_text("y" * 500, encoding="utf-8")
    context = build_job_context(_JOB, str(resume), None, max_resume_chars=40)
    assert context.resume_text.endswith("...[truncated]")
    assert context.resume_text.startswith("y" * 40)


def test_context_serialisation_never_dumps_the_resume_text() -> None:
    dumped = _context().model_dump()
    assert "resume_text" not in dumped
    assert dumped["resume_profile"]["summary"] == "Python engineer"


# --- Subtask 12.2: prompt and tolerant parse --------------------------------
def test_context_prompt_contains_both_sources_and_the_no_invention_rules() -> None:
    messages = build_context_messages(_QUESTION, "textarea", [], _context())
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "UNTRUSTED DATA" in system and "Never invent" in system
    assert _QUESTION in user
    assert "Propeller" in user and _JOB_EVIDENCE in user
    assert "Python engineer" in user and _RESUME in user


def test_parse_context_reply_handles_prose_and_normalizes_sources() -> None:
    body = json.dumps(
        {
            "job_specific": True,
            "answer": "I am drawn to Propeller's mission. My Python work fits it.",
            "sources": ["job", "cv"],
            "evidence": [_JOB_EVIDENCE, _RESUME_EVIDENCE],
            "rationale": "company mission + resume skill",
        }
    )
    decision = parse_context_reply(f"Here you go:\n```json\n{body}\n```", _QUESTION)
    assert decision.job_specific is True
    assert decision.context_sources == ["job_description", "resume"]
    assert decision.context_source == "resume+job_description"
    assert decision.evidence == [_JOB_EVIDENCE, _RESUME_EVIDENCE]


def test_parse_non_job_specific_or_unusable_reply() -> None:
    non_specific = parse_context_reply(
        '{"job_specific": false, "answer": "should be ignored"}', "Expected salary?"
    )
    assert non_specific.job_specific is False and non_specific.answer is None
    assert parse_context_reply("not json", "Q").job_specific is None


# --- Subtask 12.3: grounding and routing ------------------------------------
def _decision(
    answer: str,
    sources: list[str],
    evidence: list[str],
    *,
    question: str = _QUESTION,
    job_specific: bool = True,
) -> QuestionDecision:
    return QuestionDecision(
        question=question,
        answer=answer,
        job_specific=job_specific,
        context_sources=sources,
        evidence=evidence,
    )


def test_validate_accepts_resume_only_job_only_and_both() -> None:
    only_job = _decision(
        "I am drawn to Propeller's mission to make hiring fair.",
        ["job_description"],
        [_JOB_EVIDENCE],
    )
    assert validate_context_decision(only_job, _context(), "textarea").decided is True

    question = "What makes you a great candidate for this role?"
    only_resume = _decision(
        "I bring 6 years of Python engineering experience.",
        ["resume"],
        [_RESUME_EVIDENCE],
        question=question,
    )
    assert validate_context_decision(only_resume, _context(), "textarea").decided is True

    both = _decision(
        "Propeller's mission matters to me, and my Python engineering background fits.",
        ["resume", "job_description"],
        [_RESUME_EVIDENCE, _JOB_EVIDENCE],
        question=question,
    )
    kept = validate_context_decision(both, _context(), "textarea")
    assert kept.decided is True and kept.context_source == "resume+job_description"


def test_validate_rejects_missing_evidence_placeholder_number_and_choice() -> None:
    both_with_one_source = _decision(
        "Propeller's mission and my Python work fit.",
        ["resume", "job_description"],
        [_JOB_EVIDENCE],
        question="What makes you a great candidate?",
    )
    assert validate_context_decision(both_with_one_source, _context(), "textarea").decided is False

    placeholder = _decision(
        "[company]'s mission is fair hiring.", ["job_description"], [_JOB_EVIDENCE]
    )
    assert validate_context_decision(placeholder, _context(), "textarea").decided is False

    invented_number = _decision(
        "I bring 12 years of Python engineering experience.",
        ["resume"],
        [_RESUME_EVIDENCE],
        question="What makes you a great candidate?",
    )
    assert validate_context_decision(invented_number, _context(), "textarea").decided is False

    untraceable = _decision(
        "I am passionate about teamwork and collaboration.",
        ["job_description"],
        [_JOB_EVIDENCE],
        question="What makes you a great candidate?",
    )
    assert validate_context_decision(untraceable, _context(), "textarea").decided is False

    too_long = _decision(
        "I bring Python engineering experience. " * 40,
        ["resume"],
        [_RESUME_EVIDENCE],
        question="What makes you a great candidate?",
    )
    assert validate_context_decision(too_long, _context(), "textarea").decided is False

    for_answer = _decision(
        "Propeller's mission is fair hiring.", ["job_description"], [_JOB_EVIDENCE]
    )
    assert validate_context_decision(for_answer, _context(), "radio").decided is False


def test_company_question_requires_the_company_name() -> None:
    decision = _decision(
        "I value your mission to make hiring fair.", ["job_description"], [_JOB_EVIDENCE]
    )
    assert validate_context_decision(decision, _context(), "textarea").decided is False


def test_company_question_accepts_a_recognizable_short_company_name() -> None:
    evidence = "LEAP helps lawyers help people."
    context = _context(
        job=JobDescription(
            title="Senior Python Engineer",
            company="LEAP Legal Software",
            body=evidence + " LEAP's mission is to make hiring fair.",
        )
    )
    decision = _decision(
        "I am interested in LEAP because it helps lawyers help people.",
        ["job_description"],
        [evidence],
        question="What attracts you to LEAP as an employer?",
    )
    assert validate_context_decision(decision, context, "textarea").decided is True


async def test_context_chooser_missing_context_and_llm_failure_are_unknown() -> None:
    empty = JobAnswerContext()
    assert (await JobContextChooser(LLMSettings(api_key="k", model="m"), empty)(
        _QUESTION, "textarea", []
    )).job_specific is True

    chooser = JobContextChooser(LLMSettings(api_key="k", model="m"), _context())
    chooser._client = _FailingClient()
    decision = await chooser(_QUESTION, "textarea", [])
    assert decision.decided is False and decision.job_specific is True


class _FailingClient:
    def __init__(self) -> None:
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        raise RuntimeError("boom")


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class _RecordingStatus:
    def __init__(self) -> None:
        self.llm_lines: list[str] = []

    def llm(self, action: str, detail: str = "") -> None:
        self.llm_lines.append(f"LLM: {action}" + (f" - {detail}" if detail else ""))


def _chooser(
    answers: dict[str, str], context: JobAnswerContext | None = None
) -> ContextAwareAnswerChooser:
    return ContextAwareAnswerChooser(
        context or _context(), LLMSettings(api_key="k", model="m"), answers
    )


async def test_exact_human_answer_wins_and_context_is_not_called() -> None:
    key = normalize_question(_QUESTION)
    chooser = _chooser({key: "My own answer"})

    async def context(_q, _t, _o):
        raise AssertionError("context must not be called")

    chooser._context_chooser = context
    decision = await chooser(_QUESTION, "textarea", [])
    assert decision.answer == "My own answer" and decision.matched_key == key


async def test_job_specific_question_never_reuses_a_stale_store_answer() -> None:
    store_calls: list[str] = []

    async def store(question, field_type, options):
        store_calls.append(question)
        return QuestionDecision(question=question, answer="An old company answer")

    chooser = _chooser({})
    chooser._store = store

    async def context(_q, _t, _o):
        return QuestionDecision(
            question=_QUESTION, job_specific=True, rationale="no evidence found"
        )

    chooser._context_chooser = context
    decision = await chooser(_QUESTION, "textarea", [])
    assert decision.decided is False and decision.job_specific is True
    assert store_calls == []  # no stale prose


async def test_normal_question_still_uses_the_store_and_free_text_falls_back() -> None:
    calls: list[str] = []

    async def store(question, field_type, options):
        calls.append(question)
        if question == "Expected salary?":
            return QuestionDecision(question=question, answer="100000")
        return QuestionDecision(question=question)

    chooser = _chooser({})
    chooser._store = store
    assert (await chooser("Expected salary?", "text", [])).answer == "100000"

    async def context(question, field_type, options):
        return _decision(
            "I am drawn to Propeller's mission.",
            ["job_description"],
            [_JOB_EVIDENCE],
            question=question,
        )

    chooser._context_chooser = context
    decision = await chooser("What does working here mean to you?", "textarea", [])
    assert decision.decided is True and decision.context_source == "job_description"


async def test_factual_question_never_calls_the_context() -> None:
    async def store(question, field_type, options):
        return QuestionDecision(question=question)

    chooser = _chooser({})
    chooser._store = store

    async def context(_q, _t, _o):
        raise AssertionError("factual questions must not use the job context")

    chooser._context_chooser = context
    assert (await chooser("Expected salary?", "text", [])).decided is False
    assert (await chooser("Are you authorised to work in Australia?", "text", [])).decided is False
    assert (await chooser("Are you eligible to work in this country?", "text", [])).decided is False


async def test_context_chooser_crash_never_escapes_the_form_walk() -> None:
    async def store(question, field_type, options):
        return QuestionDecision(question=question)

    chooser = _chooser({})
    chooser._store = store

    async def context(_q, _t, _o):
        raise RuntimeError("boom")

    chooser._context_chooser = context
    decision = await chooser(_QUESTION, "textarea", [])
    assert decision.decided is False and decision.job_specific is True


def test_prefilter_recognizes_job_questions_and_ignores_normal_ones() -> None:
    assert looks_job_specific(_QUESTION, "textarea") is True
    assert looks_job_specific("What makes you a great candidate?", "text") is True
    assert looks_job_specific(
        "What makes you a great candidate based on your experience?", "text"
    ) is True
    assert looks_job_specific("Expected salary?", "text") is False
    assert looks_job_specific("Current city?", "text") is False
    assert looks_job_specific("Why this company?", "radio") is False
    assert is_free_text_field("textarea") is True and is_free_text_field("date") is False


# --- The fill path records the context answer -------------------------------
class _FakeElement:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.filled: str | None = None

    async def evaluate(self, js: str, *args):
        if args:
            self.filled = str(args[0])
        return self.label


class _FakePage:
    def __init__(self, elements: dict[str, _FakeElement]) -> None:
        self.elements = elements

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return [el for marker, el in self.elements.items() if f'"{marker}"' in selector]

    async def evaluate(self, js: str, *args):
        return ""


async def test_fill_step_records_source_evidence_and_task9_line(tmp_path) -> None:
    from src.tools.linkedin_easy_apply_fill.field_filling import _decide, _fill_step

    field = {
        "kind": "textarea",
        "type": "textarea",
        "name": "q1",
        "question": "What attracts you to Propeller as an employer?*",
        "marker": "m1",
        "required": True,
        "value": "",
        "options": [],
    }
    page = _FakePage({"m1": _FakeElement("")})
    status = _RecordingStatus()

    async def chooser(question, field_type, options):
        return validate_context_decision(
            _decision(
                "I am drawn to Propeller's mission to make hiring fair.",
                ["job_description"],
                [_JOB_EVIDENCE],
                question=question,
            ),
            _context(),
            field_type,
        )

    known, filled, unknown, records = await _fill_step(
        page, [field], {}, Settings(data_dir=tmp_path), chooser=chooser, status=status
    )
    assert (known, filled, unknown) == (1, 1, [])
    record = records[0]
    assert (record.answer_source, record.job_specific) == ("job_description", True)
    assert record.context_evidence == [_JOB_EVIDENCE]
    assert page.elements["m1"].filled.startswith("I am drawn")

    await _decide(chooser, field["question"], "textarea", [], status)
    assert any("from the job description" in line for line in status.llm_lines)


async def test_ungrounded_job_question_is_asked_and_saved_to_answers(tmp_path) -> None:
    from src.tools.answers import load_answers, normalize_question
    from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step

    question = "What makes you a great candidate for this role?*"
    field = {
        "kind": "textarea",
        "type": "textarea",
        "name": "q1",
        "question": question,
        "marker": "m1",
        "required": True,
        "value": "",
        "options": [],
    }
    page = _FakePage({"m1": _FakeElement("")})
    chooser = _chooser({})

    async def store(q, t, o):
        return QuestionDecision(question=q)

    async def context(q, t, o):
        return validate_context_decision(
            _decision(
                "I am passionate about teamwork and collaboration.",
                ["job_description"],
                [_JOB_EVIDENCE],
                question=q,
            ),
            _context(),
            t,
        )

    chooser._store = store
    chooser._context_chooser = context
    asked: list[str] = []

    async def ask(question_text, field_data):
        asked.append(question_text)
        return "I build reliable Python services."

    settings = Settings(data_dir=tmp_path)
    known, filled, unknown, records = await _fill_step(
        page,
        [field],
        {},
        settings,
        ask=ask,
        human=Task5Outcome(),
        chooser=chooser,
    )

    assert asked == [question]
    assert (known, filled, unknown) == (1, 1, [])
    assert records[0].answered_by == "human"
    assert records[0].value == "I build reliable Python services."
    stored = load_answers(settings.answers_file)
    assert stored[normalize_question(question)] == "I build reliable Python services."


# --- Threading through the fill node and a healed retry ---------------------
async def test_fill_node_builds_a_fresh_context_and_passes_it(monkeypatch, tmp_path) -> None:
    import importlib

    fill_node = importlib.import_module("src.nodes.fill")
    import src.tools.browser as browser_tools

    resume = tmp_path / "a.txt"
    resume.write_text(_RESUME, encoding="utf-8")
    settings = Settings(
        session=SessionSettings(ask_human=False),
        data_dir=tmp_path / "data",
        resume_descriptions_path=tmp_path / "descriptions.json",
    )
    monkeypatch.setattr(fill_node, "load_settings", lambda: settings)
    captured: dict = {}

    async def fake_fill(run_id, resume_path, settings=None, progress=None, context=None):
        captured["context"] = context
        return (
            Task4Outcome(
                form_open=True,
                resume_attached=True,
                reached_terminal_step=True,
                fields=[FormField(question="Q", known=True, filled=True, required=True)],
            ),
            Task5Outcome(),
        )

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        job_description=_JOB,
        task3=Task3Outcome(selected_path=str(resume), job_description=_JOB),
    )
    result = await fill_node.fill(state)

    context = captured["context"]
    assert isinstance(context, JobAnswerContext)
    assert context.job_description.title == "Senior Python Engineer"
    assert context.resume_text == _RESUME
    assert result["job_context"].sources == ["resume", "job_description"]
    assert result["task4"].job_context.resume_path == str(resume)
    assert "resume_text" not in result["job_context"].model_dump()


async def test_each_fill_builds_its_own_job_context(monkeypatch, tmp_path) -> None:
    import importlib

    fill_node = importlib.import_module("src.nodes.fill")
    import src.tools.browser as browser_tools

    resume = tmp_path / "a.txt"
    resume.write_text(_RESUME, encoding="utf-8")
    settings = Settings(
        session=SessionSettings(ask_human=False),
        data_dir=tmp_path / "data",
        resume_descriptions_path=tmp_path / "descriptions.json",
    )
    monkeypatch.setattr(fill_node, "load_settings", lambda: settings)
    captured: list[JobAnswerContext] = []

    async def fake_fill(run_id, resume_path, settings=None, progress=None, context=None):
        captured.append(context)
        return (
            Task4Outcome(
                form_open=True,
                resume_attached=True,
                reached_terminal_step=True,
                fields=[FormField(question="Q", known=True, filled=True, required=True)],
            ),
            Task5Outcome(),
        )

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)

    async def run_with(title: str) -> None:
        description = _JOB.model_copy(update={"title": title})
        await fill_node.fill(
            ApplyState(
                dry_run=False,
                browser_run_id="run-1",
                job_description=description,
                task3=Task3Outcome(selected_path=str(resume), job_description=description),
            )
        )

    await run_with("Job One")
    await run_with("Job Two")

    assert [context.job_description.title for context in captured] == ["Job One", "Job Two"]
    assert captured[0] is not captured[1]


async def test_healing_retry_rebuilds_the_context_from_the_reopened_job(
    monkeypatch, tmp_path
) -> None:
    import src.tools.self_healing.loop as healing_loop

    resume = tmp_path / "a.txt"
    resume.write_text(_RESUME, encoding="utf-8")
    settings = Settings(
        self_healing=SelfHealingSettings(max_repair_attempts=1),
        data_dir=tmp_path / "data",
        resume_descriptions_path=tmp_path / "descriptions.json",
    )
    captured: dict = {}

    async def fake_fill(run_id, resume_path, settings=None, progress=None, context=None):
        captured["context"] = context
        return (
            Task4Outcome(
                form_open=True,
                resume_attached=True,
                reached_terminal_step=True,
                fields=[FormField(question="Q", known=True, filled=True, required=True)],
            ),
            Task5Outcome(),
        )

    async def fake_reopen(target, settings, notify):
        from src.tools.self_healing.recovery import ReopenResult

        return ReopenResult(
            run_id="run-2",
            task2=Task2Outcome(job_title="Healed Job", application_form_opened=True),
            description=JobDescription(
                title="Healed Job", company="Propeller", body=_JOB.body
            ),
        )

    result = await healing_loop.heal_fill_failure(
        run_id="run-1",
        task4=Task4Outcome(form_open=True, resume_attached=False, notes="no resume control"),
        task5=Task5Outcome(),
        settings=settings,
        target=None,
        resume_path=str(resume),
        description=_JOB,
        context=build_job_context(_JOB, str(resume), settings.resume_descriptions_file),
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        reopen_fn=fake_reopen,
        fill_fn=fake_fill,
    )

    assert result.recovered is True
    assert captured["context"].job_description.title == "Healed Job"
    assert captured["context"].resume_path == str(resume)


async def _value(value):
    return value


def _captured(tmp_path):
    from src.tools.self_healing.models import CapturedFailure, FailureEvidence

    return CapturedFailure(
        fingerprint="task12",
        category="resume_control_missing",
        symptom="no resume control",
        bundle_dir=str(tmp_path / "bundle"),
        evidence=FailureEvidence(error="no resume control"),
    )


def _record(tmp_path):
    from src.tools.self_healing.models import FailureRecord

    (tmp_path / "bundle").mkdir(parents=True, exist_ok=True)
    return FailureRecord(
        fingerprint="task12",
        category="resume_control_missing",
        bug_id="BUG-999",
        bug_path=str(tmp_path / "bundle" / "bug.md"),
        bundle_dir=str(tmp_path / "bundle"),
        symptom="no resume control",
    )
