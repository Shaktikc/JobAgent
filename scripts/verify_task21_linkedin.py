"""Verify optional-question skipping in the dedicated JobAgent LinkedIn browser.

Default: run the production fill filter with an unknown chooser, without filling
required answers or navigating. --walk enables the normal human-answer flow and
navigation, always stopping before Submit. Stop any other automation before walking.
Evidence stays in the gitignored debug directory; no optional answers are logged.
"""

import argparse
import asyncio
import base64
import json

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.linkedin_easy_apply_fill.required_only import is_required_field
from src.tools.llm_answers import QuestionDecision

SNAPSHOT = """(markers) => JSON.stringify(markers.map(marker => {
  const host = document.querySelector('[data-autojob-fill="' + marker + '"]');
  const el = host && (host.control || host.querySelector('input,select,textarea') || host);
  return el ? [marker,el.value,el.checked,el.getAttribute('aria-checked')] : [marker,null];
}))"""


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--walk", action="store_true")
    parser.add_argument("--human-timeout", type=float, default=300)
    args = parser.parse_args()
    settings = load_settings()
    settings.session.ask_human = True
    settings.session.ask_timeout_seconds = args.human_timeout
    folder = settings.debug_dir / "task21"
    folder.mkdir(parents=True, exist_ok=True)
    browser = BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    await browser.start()
    try:
        page = None
        for candidate in await browser.get_pages():
            if "linkedin.com/jobs/" in await candidate.get_url():
                page = candidate
                break
        if page is None:
            raise RuntimeError("No LinkedIn jobs tab in the dedicated browser")
        opened, _, fields, step = await read_form(page)
        if not opened:
            raise RuntimeError("Open the Easy Apply form before verifying")
        optional = [f for f in fields if not is_required_field(f)]
        markers = [f["marker"] for f in optional]
        before = await page.evaluate(SNAPSHOT, markers)
        store_before = (
            settings.answers_file.read_bytes() if settings.answers_file.exists() else None
        )
        calls = []

        async def unknown(question, kind, options):
            calls.append(question)
            assert question not in {f["question"] for f in optional}
            return QuestionDecision(question=question)

        human = Task5Outcome()
        answers = load_answers(settings.answers_file)
        if args.walk:
            outcome = await _task4_on_page(
                page, browser, None, answers, settings, print, human=human, chooser=unknown,
            )
            assert not outcome.submitted
            report = outcome.model_dump()
        else:
            known, filled, unknown_fields, records = await _fill_step(
                page, fields, answers, settings, chooser=unknown, human=human,
            )
            assert before == await page.evaluate(SNAPSHOT, markers)
            store_after = (
                settings.answers_file.read_bytes() if settings.answers_file.exists() else None
            )
            assert store_before == store_after
            assert human.asked == 0
            report = {"known": known, "filled": filled, "unknown": unknown_fields,
                      "records": [r.model_dump() for r in records],
                      "optional_values_unchanged": True, "answer_store_unchanged": True}
        report.update({"step_before": step, "optional_controls": len(optional),
                       "optional_questions": list(dict.fromkeys(f["question"] for f in optional)),
                       "chooser_questions": calls, "human": human.model_dump()})
        name = "walk" if args.walk else "skip-check"
        (folder / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (folder / f"{name}.png").write_bytes(base64.b64decode(await page.screenshot()))
        print(json.dumps(report, ensure_ascii=True))
    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
