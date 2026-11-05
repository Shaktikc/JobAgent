"""Bounded answer attempts shared by normal filling and validation recovery."""

from src.state import FormField
from src.state.validation import RequiredAnswerAttempt
from src.tools.job_context_answers import record_decision
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_validation.required_controls import (
    apply_answer,
    group_for,
    held_answer,
    usable_answer,
)
from src.tools.llm_answers import QuestionDecision


class AnswerAttempts:
    """One chooser call and one human prompt per question per step."""

    def __init__(self, settings, human, chooser, ask, notify, answers=None):
        self.settings, self.human = settings, human
        self.chooser, self.asker, self.notify = chooser, ask, notify
        self.step = ""
        self._entries = {}
        self.answers = answers

    def _entry(self, question, kind):
        key = (self.step, question, kind)
        return self._entries.setdefault(key, RequiredAnswerAttempt(question=question))

    def audit(self):
        return [
            row.model_copy(deep=True) for key, row in self._entries.items() if key[0] == self.step
        ]

    def unresolved_issues(self, fields):
        failed = {row.question for row in self.audit() if row.human_prompted and row.failure}
        return [
            dict(
                question=field.get("question", ""),
                field=field,
                message="Human skipped or did not finish this required answer",
            )
            for field in fields
            if field.get("question") in failed
        ]

    async def choose(self, question, kind, options):
        entry = self._entry(question, kind)
        if entry.automatic_attempted or self.chooser is None:
            return QuestionDecision(question=question)
        entry.automatic_attempted = True
        emit_step(self.notify, f"Answering {question!r} from grounded sources...")
        return await self.chooser(question, kind, options)

    async def ask(self, question, field):
        entry = self._entry(question, field.get("type", ""))
        if not self.settings.session.ask_human or self.asker is None:
            entry.failure = "human answers are disabled"
            return None
        if entry.human_prompted:
            return None
        entry.human_prompted = True
        emit_step(self.notify, f"Asking you to answer {question!r} in the form...")
        answer = await self.asker(question, field)
        if answer is None:
            entry.failure = "human skipped, timed out, or the banner was unavailable"
        elif self.answers is not None:
            from src.tools.answers import normalize_question

            self.answers[normalize_question(question)] = answer
        return answer


async def recover_required(page, issues, outcome, attempts, read):
    """Resolve at most five blocking questions, using existing grounded sources."""
    from src.tools.linkedin_easy_apply_fill.required_only import is_required_field

    handled = set()
    for issue in issues:
        field = issue.get("field") or {}
        key = (
            field.get("question"),
            field.get("kind"),
            "" if field.get("kind") == "checkbox" else field.get("name"),
        )
        if key in handled:
            continue
        handled.add(key)
        if len(handled) > 5:
            return False, "required-answer recovery exceeded five questions on this step"
        if not is_required_field(field):
            return False, "the rejected question has no visible required marker"
        group = group_for(field, (await read(page))[2])
        if not group or not all(is_required_field(row) for row in group):
            return False, "the required question disappeared or changed"
        question, kind = field["question"], field.get("type", "")
        if field.get("kind") in {"radio", "checkbox"}:
            kind = field["kind"]
        entry = attempts._entry(question, kind)
        if entry.human_prompted and entry.failure:
            return False, entry.failure  # A partial value left on the form is not an answer.
        record = next(
            (
                row
                for row in reversed(outcome.fields)
                if row.question == question
                and row.field_type == kind
                and (not field.get("name") or row.name == field["name"])
            ),
            None,
        )
        answer, source, decision = held_answer(group), "form", None
        if not answer and record and record.known:
            answer, source = record.value, record.answered_by
        options = (
            [row.get("option", "") for row in group]
            if field.get("kind") in {"radio", "checkbox"}
            else [row.get("text", "") for row in field.get("options", [])]
        )
        if not usable_answer(group, answer):
            decision = await attempts.choose(question, kind, options)
            answer, source = decision.answer if decision.decided else None, "llm"
        if not usable_answer(group, answer):
            # Markers belong to the current render, including after the chooser call.
            group = group_for(field, (await read(page))[2])
            if not group:
                return False, "the required question disappeared before the human prompt"
            options = (
                [row.get("option", "") for row in group]
                if field.get("kind") in {"radio", "checkbox"}
                else [row.get("text", "") for row in group[0].get("options", [])]
            )
            prompt = dict(
                group[0],
                type=kind,
                markers=[row["marker"] for row in group],
                options=options
                if field.get("kind") in {"radio", "checkbox"}
                else field.get("options", []),
            )
            answer, source = await attempts.ask(question, prompt), "human"
            decision = None
        if not usable_answer(group, answer):
            entry.failure = entry.failure or "no grounded or completed human answer was available"
            return False, entry.failure
        if not await apply_answer(page, field, answer, read):
            entry.failure = "the answer could not be verified in the live control"
            return False, entry.failure
        replacement = FormField(
            question=question,
            name=field.get("name", ""),
            field_type=kind,
            value=answer,
            required=True,
            known=True,
            filled=True,
            answered_by=source,
            options=options,
        )
        if decision is not None and decision.decided:
            record_decision(replacement, decision)
        outcome.known_fields += int(record is None or not record.known)
        outcome.filled_fields += int(record is None or not record.filled)
        if record is None:
            outcome.fields.append(replacement)
        else:
            outcome.fields[outcome.fields.index(record)] = replacement
        outcome.unknown_fields = [q for q in outcome.unknown_fields if q != question]
        entry.failure = ""
    return True, ""
