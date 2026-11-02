"""Exercise one real required-phone validation and restore its known value.

Use only the dedicated AutoJobApply browser with an open contact step. The
existing phone number stays in memory: clearing it triggers required-field
feedback, then production recovery re-enters the same known value and advances.
No answer is invented, no final application is submitted, and no value is logged.
"""

import argparse
import asyncio
import base64
import json
import time

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import FormField, Task4Outcome
from src.tools.browser import _marker_element
from src.tools.forms import pick_next_button
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_field
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.form_walk import _blur_active, _form_signature
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.linkedin_validation.navigation import finish_advance


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    args = parser.parse_args()
    settings = load_settings()
    browser = BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    await browser.start()
    try:
        page = field = None
        for candidate in await browser.get_pages():
            if "linkedin.com/jobs/" not in await candidate.get_url():
                continue
            current = await read_form(candidate)
            field = next(
                (
                    f
                    for f in current[2]
                    if f.get("type") == "tel" and "*" in f.get("question", "") and f.get("value")
                ),
                None,
            )
            if field:
                page = candidate
                break
        if page is None:
            raise RuntimeError("Open a contact step with a known required phone number")
        original = field["value"]
        record = FormField(
            question=field["question"],
            name=field["name"],
            value=original,
            known=True,
            filled=True,
            required=True,
            answered_by="form",
        )
        try:
            element = await _marker_element(page, "data-autojob-fill", field["marker"])
            await _fill_field(element, field, "")
            button = pick_next_button(await read_form_buttons(page))
            if button:
                await _blur_active(page)
                await (await _marker_element(page, "data-autojob-btn", button["marker"])).click()
            deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
            issues = []
            while time.monotonic() < deadline:
                current = await read_form(page)
                issues = await read_rejections(page, current[2])
                if issues:
                    break
                await asyncio.sleep(0.25)
            if not issues:
                raise RuntimeError("LinkedIn did not expose required-phone validation")
            outcome = Task4Outcome(fields=[record], known_fields=1, filled_fields=1)
            previous = _form_signature(current[1], current[2], current[3])
            messages = []
            final = await finish_advance(
                page,
                current,
                previous,
                settings,
                messages.append,
                outcome,
                None,
                {},
                read=read_form,
                buttons=read_form_buttons,
                signature_of=_form_signature,
                blur=_blur_active,
            )
            advanced = _form_signature(final[1], final[2], final[3]) != previous
            report = {
                "detected_real_rejection": True,
                "error_labels": [row["question"] for row in issues],
                "step_advanced": advanced,
                "validation_failed": bool(outcome.validation.issues),
                "reported_recovery": any("Invalid input corrected" in str(m) for m in messages),
                "submitted": outcome.submitted,
                "restored_known_value": record.value == original,
            }
            folder = settings.debug_dir / "task20_linkedin"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "recovery.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            (folder / "recovery.png").write_bytes(base64.b64decode(await page.screenshot()))
            print("TASK20_REAL_RECOVERY " + json.dumps(report))
            assert advanced and report["reported_recovery"] and not outcome.validation.issues
            assert not outcome.submitted
        finally:
            # If the check stops before navigation, restore the original value
            # rather than leaving a deliberately blank contact field behind.
            _, _, remaining, _ = await read_form(page)
            phone = next(
                (
                    f
                    for f in remaining
                    if f.get("type") == "tel" and f.get("question") == field["question"]
                ),
                None,
            )
            if phone:
                element = await _marker_element(page, "data-autojob-fill", phone["marker"])
                if element:
                    await _fill_field(element, phone, original)
    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
