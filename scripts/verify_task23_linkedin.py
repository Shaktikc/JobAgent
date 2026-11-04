"""Verify Task 3/10 model routing in the dedicated LinkedIn browser.

Launch the dedicated profile or attach to a jobs tab with --cdp-url.
Optional --resume-model/--answers-model
overrides affect this process only. --walk fills the dynamic Easy Apply form,
including Task 5 prompts, and stops before submission. Request evidence records
model IDs and HTTP status only; prompts, answers, and credentials are excluded.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from browser_use import BrowserSession
from openai import AsyncOpenAI

from src.configuration import load_settings
from src.llm_model_routing import answer_llm_settings, resume_llm_settings
from src.main import _log_models, _silence_windows_pipe_noise
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.browser import build_browser
from src.tools.job_context import build_job_context
from src.tools.linkedin_best_matching_resume import list_resume_files, read_job_description
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.linkedin_easy_apply_open import open_easy_apply_form
from src.tools.resume_descriptions import (
    described_candidates,
    load_descriptions,
    pick_best_resume,
)


@asynccontextmanager
async def record_requests(records):
    """Observe real SDK HTTP requests without changing their model or reply."""
    clients = []

    async def request_hook(request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            request.extensions["task23_record"] = len(records)
            records.append({"model": body.get("model"), "http_status": None})

    async def response_hook(response):
        index = response.request.extensions.get("task23_record")
        if index is not None:
            records[index]["http_status"] = response.status_code
            await response.aread()
            try:
                records[index]["response_model"] = response.json().get("model")
            except ValueError:
                pass

    def client_factory(**kwargs):
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(
                event_hooks={"request": [request_hook], "response": [response_hook]},
            ),
        )
        clients.append(client)
        return client

    with patch("openai.AsyncOpenAI", client_factory):
        try:
            yield
        finally:
            for client in clients:
                await client.close()


async def verify(args):
    settings = load_settings()
    if args.resume_model:
        settings.llm.resume_model = args.resume_model
    if args.answers_model:
        settings.llm.answers_model = args.answers_model
    resume_llm = resume_llm_settings(settings)
    answer_llm = answer_llm_settings(settings)
    if not resume_llm.configured or not answer_llm.configured:
        raise ValueError("Configure credentials and both resolved task models")
    if resume_llm.model == answer_llm.model:
        raise ValueError("Use two distinct model IDs for routing verification")
    settings.session.ask_human = True
    settings.session.ask_timeout_seconds = args.human_timeout
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = settings.debug_dir / "task23" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    # A fresh derived cache ensures a previous run cannot hide a Task 10 call.
    settings.derived_answers_path = folder / "derived_answers.json"
    _log_models(settings)
    report = {
        "models": {"task3": resume_llm.model, "task10": answer_llm.model,
                   "general": settings.llm.model,
                   "self_healing": settings.self_healing.repair_model},
        "requests": [], "walk": args.walk, "passed": False,
    }
    browser = (
        BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
        if args.cdp_url else build_browser(settings)
    )
    page = None
    try:
        await browser.start()
        if args.cdp_url:
            for candidate in await browser.get_pages():
                if "linkedin.com/jobs/" in await candidate.get_url():
                    page = candidate
                    break
        else:
            job_query = f"&currentJobId={args.job_id}" if args.job_id else ""
            page = await browser.new_page(
                "https://www.linkedin.com/jobs/search/"
                "?keywords=software%20engineer&f_AL=true&f_TPR=r604800"
                + job_query
            )
            await asyncio.sleep(5)
        if page is None:
            raise RuntimeError("No LinkedIn jobs tab in the dedicated browser")
        description = await read_job_description(page)
        if not description.is_read:
            raise RuntimeError("Select a job with a readable description first")
        report["job"] = {"title": description.title, "company": description.company}
        candidates = described_candidates(
            list_resume_files(settings.resumes_dir),
            load_descriptions(settings.resume_descriptions_file),
        )
        if not candidates:
            raise RuntimeError("Describe the resume pool before this live check")
        async with record_requests(report["requests"]):
            match = await pick_best_resume(description, candidates, settings)
            report["resume"] = {
                "selected": Path(match.selected_path).name if match.selected_path else None,
                "fit": match.fit,
            }
            print("RESUME:", json.dumps(report["resume"]), flush=True)
            if not match.selected_path:
                raise RuntimeError("No resume matched; select another eligible job")
            if args.walk:
                opened, result = await open_easy_apply_form(page, settings, print)
                if not opened:
                    raise RuntimeError(result.notes or "Easy Apply did not open")
                human = Task5Outcome()
                outcome = await _task4_on_page(
                    page, browser, match.selected_path, load_answers(settings.answers_file),
                    settings, print, human=human,
                    context=build_job_context(
                        description, match.selected_path, settings.resume_descriptions_file,
                    ),
                )
                assert not outcome.submitted
                report["form"] = {
                    "open": outcome.form_open, "steps_advanced": outcome.steps_advanced,
                    "terminal": outcome.reached_terminal_step,
                    "resume_attached": outcome.resume_attached,
                    "filled_store_answers": sum(
                        bool(field.filled and field.source_keys and field.answered_by == "llm")
                        for field in outcome.fields
                    ),
                    "human_prompts": human.asked, "submitted": outcome.submitted,
                    "validation_skipped": outcome.validation.skipped,
                    "notes": outcome.notes,
                }
                successful = {
                    row["model"] for row in report["requests"]
                    if row["http_status"] and 200 <= row["http_status"] < 300
                }
                assert answer_llm.model in successful, "No successful real Task 10 request"
                assert report["form"]["filled_store_answers"], "No grounded store answer filled"
            report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if page is not None:
            report["url"] = await page.get_url()
            opened, title, fields, step = await read_form(page)
            report["current_step"] = {
                "open": opened, "title": title, "step": step,
                "required_questions": [field.get("question") for field in fields
                                       if field.get("required")],
            }
            report["field_labels"] = [
                {key: field.get(key) for key in ("kind", "name", "question", "required")}
                for field in fields
            ]
            markup = await page.evaluate("""() => {
              const modal = document.querySelector('dialog[open], .jobs-easy-apply-modal');
              return modal ? modal.outerHTML : '';
            }""")
            (folder / "form_markup.html").write_text(str(markup), encoding="utf-8")
            (folder / "browser.png").write_bytes(base64.b64decode(await page.screenshot()))
        (folder / "verification.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8",
        )
        print("EVIDENCE:", folder, flush=True)
        print("RESULT:", json.dumps(report, ensure_ascii=True), flush=True)
        await browser.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url")
    parser.add_argument("--resume-model")
    parser.add_argument("--answers-model")
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--walk", action="store_true")
    parser.add_argument("--human-timeout", type=float, default=10)
    args = parser.parse_args()
    if args.human_timeout <= 0:
        parser.error("--human-timeout must be positive")
    _silence_windows_pipe_noise()
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
