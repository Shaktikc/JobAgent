"""One independent store lookup before a required question reaches the human."""

import asyncio

from src.tools.answers import answer_echoes_question, normalize_question
from src.tools.derived_answers import save_derived_answer
from src.tools.forms import answers_match, is_prompt_answer
from src.tools.llm_answer_reasoning import (
    build_reasoning_messages,
    parse_reasoning_reply,
    validate_decision,
)
from src.tools.llm_answers import QuestionDecision
from src.tools.token_usage.runtime import tracked_completion


class SelectLabels(list):
    """Present visible labels to the chooser and retain valid HTML option values."""

    def __init__(self, options):
        super().__init__(option.get("text", "") for option in options)
        self.values = [
            option["value"] for option in options
            if option.get("value") and not is_prompt_answer(option.get("text", ""))
        ]


def fits_control(answer, kind, options):
    if not answer or not answer.strip():
        return False
    if kind == "checkbox":
        from src.tools.linkedin_easy_apply_fill.checkbox_groups import (
            leaves_single_unchecked,
            selected_options,
        )

        return bool(selected_options(answer, options)) or leaves_single_unchecked(answer, options)
    if kind == "radio" or kind.startswith("select"):
        if isinstance(options, SelectLabels) and answer in options.values:
            return True
        return any(not is_prompt_answer(opt) and answers_match(opt, answer) for opt in options)
    return True


def _usable_source(key, value):
    return (
        isinstance(value, str) and bool(value.strip())
        and not answer_echoes_question(key, value) and not is_prompt_answer(value)
    )


async def second_look(llm, answers, question, kind, options, cache_path):
    """Return a grounded decision or an unknown decision with a value-free reason."""
    unknown = QuestionDecision(question=question, second_look=True)
    try:
        key = normalize_question(question)
        store = {k: v for k, v in answers.items() if _usable_source(k, v)}
        exact = store.pop(key, None)
        if fits_control(exact, kind, options):
            return QuestionDecision(
                question=question, answer=exact, matched_key=key, source_keys=[key],
                source_summary=f"{key!r}: {exact!r}", second_look=True,
            )

        from openai import AsyncOpenAI

        messages = build_reasoning_messages(question, kind, options, answers)
        messages[0]["content"] += (
            "\nThe first pass found no grounded answer. Look again for a missed paraphrase, "
            "abbreviation, synonym, or related experience, education or authorization entry. "
            "Ignore placeholders and question echoes. For checkbox groups you may copy a "
            "comma-separated selection of listed options."
        )
        async with AsyncOpenAI(
            api_key=llm.api_key, base_url=llm.base_url, timeout=llm.timeout_seconds, max_retries=0,
        ) as client:
            async with asyncio.timeout(llm.timeout_seconds):
                response = await tracked_completion(
                    client, model=llm.model, messages=messages, temperature=llm.temperature,
                )
        reply = response.choices[0].message.content
        allowed = list(options)
        if isinstance(options, SelectLabels):
            allowed.extend(options.values)
        decision = validate_decision(
            parse_reasoning_reply(reply, question, store), store,
            [] if kind == "checkbox" else allowed,
        )
        if (not fits_control(decision.answer, kind, options)
                or not _usable_source(question, decision.answer)):
            unknown.rationale = "no grounded answer fits the control"
            return unknown
        decision.second_look = True
        if decision.derived:
            save_derived_answer(
                cache_path, question, decision.answer, decision.source_keys,
                {k: store[k] for k in decision.source_keys}, decision.rationale,
            )
        return decision
    except Exception as exc:
        unknown.rationale = f"store re-read failed ({type(exc).__name__})"
        return unknown
