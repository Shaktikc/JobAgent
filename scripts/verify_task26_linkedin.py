"""Verify slow completion on a real text question, restoring the store afterward."""

import argparse
import asyncio
import base64
import json
from unittest.mock import patch

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import Task5Outcome
from src.tools.answers import load_answers, normalize_question
from src.tools.browser import _marker_element
from src.tools.linkedin_ask_human import ask_human_for_answer, store
from src.tools.linkedin_easy_apply_fill.form_queries import read_form


async def verify(args):
    settings = load_settings()
    settings.session.ask_poll_seconds = 0.1
    settings.session.ask_timeout_seconds = 2
    folder = settings.debug_dir / "task26"
    folder.mkdir(parents=True, exist_ok=True)
    browser = BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    await browser.start()
    waiter = None
    backup = None
    element = None
    try:
        page = None
        for candidate in await browser.get_pages():
            if "linkedin.com/jobs/" in await candidate.get_url():
                page = candidate
                break
        assert page is not None, "Open a LinkedIn jobs tab first"
        current = await read_form(page)
        matches = [f for f in current[2] if args.question.lower() in f["question"].lower()]
        assert len(matches) == 1 and matches[0]["type"] == "text"
        field = matches[0]
        original = field.get("value", "")
        assert original, "Fill this question with an approved fact before verification"
        final = original + " years" if original.isdigit() else original
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        backup = settings.answers_file.read_bytes()
        answers = load_answers(settings.answers_file)
        key = normalize_question(field["question"])
        answers.pop(key, None)
        settings.answers_file.write_text(json.dumps(answers), encoding="utf-8")
        await element.fill("")
        human = Task5Outcome()
        with patch.object(store, "save_answer", wraps=store.save_answer) as writer:
            waiter = asyncio.create_task(
                ask_human_for_answer(
                    page,
                    field["question"],
                    "text",
                    "",
                    settings,
                    print,
                    human,
                    markers=[field["marker"]],
                    name=field.get("name"),
                )
            )
            for _ in range(100):
                if (
                    str(
                        await page.evaluate("() => !!document.getElementById('autojob-unknown')")
                    ).lower()
                    == "true"
                ):
                    break
                await asyncio.sleep(0.05)
            observations = []
            for index in range(1, len(final) + 1):
                await element.fill(final[:index])
                await asyncio.sleep(0.45)
                assert not waiter.done(), "Run advanced during typing"
                assert key not in load_answers(settings.answers_file), "Partial answer saved"
                assert writer.call_count == 0
                observations.append({"prefix_length": index, "saved": False})
            await page.evaluate("() => document.getElementById('autojob-unknown-done').click()")
            await asyncio.sleep(0.3)
            status = await page.evaluate(
                "() => document.getElementById('autojob-unknown-status').textContent"
            )
            assert "Saved" in status
            shot = await page.screenshot()
            (folder / "saved.png").write_bytes(base64.b64decode(shot))
            assert await asyncio.wait_for(waiter, 5) == final
            assert load_answers(settings.answers_file)[key] == final
            assert writer.call_count == 1 and human.answered == 1
            report = {
                "question": field["question"],
                "observations": observations,
                "writes": writer.call_count,
                "returned_complete": True,
                "submitted": False,
                "original_store_restored_after_check": True,
            }
            (folder / "completion.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
    finally:
        if waiter and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        if backup is not None:
            settings.answers_file.write_bytes(backup)
        if element is not None:
            await element.fill(original)
        await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--question", required=True)
    asyncio.run(verify(parser.parse_args()))
