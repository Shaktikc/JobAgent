"""Force the first context miss on an open LinkedIn question and verify the live re-read."""

import argparse
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import Task5Outcome
from src.tools.browser import _marker_element
from src.tools.job_context import build_job_context
from src.tools.job_context_answers import build_fill_chooser, looks_job_specific
from src.tools.linkedin_best_matching_resume import read_job_description
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.required_only import only_required_fields
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision


async def verify(cdp_url, resume):
    settings = load_settings()
    browser = BrowserSession(cdp_url=cdp_url, keep_alive=True)
    await browser.start()
    try:
        for page in await browser.get_pages():
            if "linkedin.com/jobs/" in await page.get_url():
                fields = only_required_fields((await read_form(page))[2])
                field = next((f for f in fields if looks_job_specific(f["question"], f["type"])),
                             None)
                if field:
                    break
        else:
            raise RuntimeError("Open a screening step with a required job-specific question")
        description = await read_job_description(page)
        assert description.body, "No readable job description on this tab"
        context = build_job_context(description, str(resume), settings.resume_descriptions_file)
        assert context.resume_text, "No readable resume"
        chooser = build_fill_chooser(settings, {}, context)
        ask = AsyncMock(return_value=None)
        attempts = AnswerAttempts(settings, Task5Outcome(), chooser, ask, print, {})
        question = field["question"]
        original = field.get("value") or ""
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        try:
            if original:
                await element.fill("")
            field = next(f for f in (await read_form(page))[2] if f["question"] == question)
            first_miss = QuestionDecision(question=question, job_specific=True, rationale="test")
            real_read = chooser._context_decision

            async def force_first(*args, **kwargs):
                return await real_read(*args, **kwargs) if kwargs.get("second_look") else first_miss

            with patch.object(chooser, "_context_decision", force_first):
                _, _, _, records = await _fill_step(
                    page, [field], {}, settings, ask=attempts.ask, chooser=attempts.choose,
                )
            record, = records
            assert record.filled and record.second_look, attempts.human.notes
            assert record.answer_source and record.context_evidence and record.answered_by == "llm"
            actual = next(f for f in (await read_form(page))[2] if f["question"] == question)
            assert actual["value"] == record.value
            ask.assert_not_awaited()
            print(f"PASS {description.company}: {question} ({record.answer_source}, zero prompts)")
        finally:
            await element.fill(original)
    finally:
        await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--resume", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(verify(args.cdp_url, args.resume))
