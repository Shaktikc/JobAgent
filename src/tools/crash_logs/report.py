"""Render a crash bundle's human-readable ``report.md`` (Task 33)."""

from __future__ import annotations

import json

from src.tools.crash_logs.models import CrashRecord


def _value(value, default: str = "(unknown)") -> str:
    text = str(value) if value not in (None, "") else default
    return text


def render_report(record: CrashRecord) -> str:
    exception = record.get("exception") or {}
    run = record.get("run") or {}
    job = record.get("job") or {}
    browser = record.get("browser") or {}
    healing = record.get("self_healing") or {}
    run_log = record.get("run_log") or {}
    lines = [
        f"# AutoJobApply crash — {record.get('kind', 'crash')}",
        "",
        f"- **Crash id:** {record.get('crash_id', '')}",
        f"- **Captured:** {record.get('captured_at', '')}",
        f"- **Kind:** {record.get('kind', '')}",
        f"- **Stage:** {_value(record.get('stage'))}",
        f"- **Exit code:** {_value(record.get('exit_code'), '(not exiting)')}",
        f"- **Exception:** {_value(exception.get('type'), '(none)')}: "
        f"{exception.get('message') or record.get('message') or ''}",
        f"- **Run id:** {_value(run.get('run_id'))}",
        f"- **PID / duration:** {run.get('pid', '')} / {run.get('duration_seconds', '')}s",
        f"- **Command:** `{' '.join(map(str, run.get('argv') or []))}`",
        f"- **Git:** {_value(run.get('git_commit'))} (dirty={run.get('git_dirty')})",
        f"- **Python / platform:** {run.get('python', '')} / {run.get('platform', '')}",
        "",
        "## Job",
        "",
        f"- **Title:** {_value(job.get('title'))}",
        f"- **Company:** {_value(job.get('company'))}",
        f"- **Job id:** {_value(job.get('id'))}",
        f"- **URL:** {_value(job.get('url'))}",
        "",
        "## Browser",
        "",
        f"- **Page URL:** {_value(browser.get('page_url'))}",
        f"- **Page title:** {_value(browser.get('page_title'))}",
        f"- **Screenshot:** {_value(browser.get('screenshot'), '(not captured)')}",
        f"- **Snapshot error:** {_value(browser.get('error'), '(none)')}",
        "",
        "## Self-healing",
        "",
    ]
    if healing.get("bundle") or healing.get("bug_id"):
        lines += [
            f"- **Bug id:** {_value(healing.get('bug_id'))}",
            f"- **Bundle:** {_value(healing.get('bundle'))} (screenshot/DOM live there)",
            f"- **Attempts:** {healing.get('attempts', 0)}; "
            f"recovered={healing.get('recovered', False)}",
            f"- **Stop reason:** {_value(healing.get('stop_reason'), '(none)')}",
        ]
    else:
        lines.append("(no self-healing bundle for this crash)")
    lines += ["", "## Errors", ""]
    lines.extend(f"- {error}" for error in record.get("errors") or ["(none)"])
    lines += ["", "## Recent state log", ""]
    lines.extend(f"- {entry}" for entry in (record.get("log") or ["(none)"])[-40:])
    extra = record.get("context") or {}
    if extra:
        lines += ["", "## Context", "", "```json", json.dumps(extra, indent=2, default=str), "```"]
    lines += [
        "",
        "## Traceback",
        "",
        "```",
        exception.get("traceback") or "(none)",
        "```",
        "",
        "## Run log",
        "",
        f"- **Full log:** {_value(run_log.get('path'), '(not written)')} "
        f"({run_log.get('total_lines', 0)} lines)",
        "- **Tail:** `run.log` in this bundle",
        "",
        "## Truncation",
        "",
    ]
    lines.extend(f"- {note}" for note in record.get("truncation") or ["(nothing was clipped)"])
    lines += [
        "",
        "## Files",
        "",
        "- `crash.json` — structured record",
        "- `traceback.txt` — full traceback with chained causes",
        "- `state.json` — redacted graph state",
        "- `run.log` — run-log tail at the crash",
        "- `env.json` — platform, git, argv, settings",
        "- `screenshot.png`, `dom.html`, `page.txt`, `console.log` — when a page was live",
        "",
    ]
    return "\n".join(lines)


__all__ = ["render_report"]
