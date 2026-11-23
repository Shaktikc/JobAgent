"""Verify the pre-banner lookup on an open LinkedIn screening step, without navigating."""

import argparse
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import Task5Outcome
from src.tools.answers import load_answers, normalize_question
from src.tools.browser import _marker_element
from src.tools.job_context_answers import build_fill_chooser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.required_only import only_required_fields
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision


async def verify(cdp_url):
    settings = load_settings()
    settings.session.ask_timeout_seconds = 15
    settings.session.ask_poll_seconds = 0.1
    store = load_answers(settings.answers_file)
    browser = BrowserSession(cdp_url=cdp_url, keep_alive=True)
    await browser.start()
    try:
        for page in await browser.get_pages():
            if "linkedin.com/jobs/" in await page.get_url():
                fields = only_required_fields((await read_form(page))[2])
                field = next((f for f in fields if f.get("type") == "text"
                              and normalize_question(f["question"]) in store), None)
                if field:
                    break
        else:
            raise RuntimeError("Open a required text question with an exact stored answer")
        question = field["question"]
        key = normalize_question(question)
        value = store[key]
        original = field.get("value") or ""
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        with TemporaryDirectory(dir=settings.data_dir) as temp:
            settings.answers_path = Path(temp) / "answers.json"
            settings.derived_answers_path = Path(temp) / "derived_answers.json"
            try:
                for mode in ("forced miss", "ordinary", "unsupported"):
                    await element.fill("")
                    current = [f for f in (await read_form(page))[2] if f["question"] == question]
                    assert len(current) == 1 and not current[0].get("value")
                    answers = {"verification reference": "unavailable"} if mode == "unsupported" \
                        else store.copy()
                    human = Task5Outcome()

                    async def miss(*args):
                        return QuestionDecision(question=question)

                    async def ask(q, control, mode=mode, human=human):
                        assert mode == "unsupported", f"Unexpected banner during {mode}"
                        return await ask_human_for_answer(
                            page, q, control["type"], "", settings, print, human,
                            markers=[control["marker"]], name=control.get("name"),
                        )

                    chooser = build_fill_chooser(settings, answers, None) if mode == "ordinary" \
                        else miss
                    attempts = AnswerAttempts(settings, human, chooser, ask, print, answers)
                    async with asyncio.TaskGroup() as tasks:
                        fill = tasks.create_task(_fill_step(
                            page, current, answers, settings, ask=attempts.ask,
                            human=human, chooser=attempts.choose,
                        ))
                        if mode == "unsupported":
                            async with asyncio.timeout(settings.llm.timeout_seconds + 20):
                                while str(await page.evaluate(
                                    "() => !!document.getElementById('autojob-unknown-done')"
                                )).lower() != "true":
                                    assert not fill.done(), "Missing completion banner"
                                    await asyncio.sleep(0.1)
                            await element.fill(value)
                            async with asyncio.timeout(10):
                                while str(await page.evaluate(
                                    "() => document.querySelector('#autojob-unknown-done:enabled')"
                                    " !== null"
                                )).lower() != "true":
                                    await asyncio.sleep(0.1)
                            assert key not in load_answers(settings.answers_file)
                            await page.evaluate(
                                "() => document.getElementById('autojob-unknown-done').click()"
                            )
                    record = fill.result()[3][0]
                    assert record.filled and record.value == value
                    fresh = (await read_form(page))[2]
                    actual = next(f for f in fresh if f["question"] == question)
                    assert actual["value"] == value
                    assert human.asked == human.answered == int(mode == "unsupported")
                    if mode == "unsupported":
                        assert load_answers(settings.answers_file)[key] == value
                        assert attempts.audit()[0].second_attempted
                    else:
                        assert record.answered_by == "llm" and not settings.answers_file.exists()
                        if mode == "forced miss":
                            assert record.second_look
                    print(f"PASS {mode}: {question!r}, banners={human.asked}", flush=True)
            finally:
                await element.fill(original)
    finally:
        await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    asyncio.run(verify(parser.parse_args().cdp_url))
