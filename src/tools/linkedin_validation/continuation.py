"""Restore filtered results when a rejected Easy Apply came from a job permalink."""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from src.date_range import normalize_date_range
from src.tools.linkedin import build_jobs_search_url, is_linkedin_url


def results_url(search_url: str, query: str, date_range: str) -> str:
    parsed = urlsplit(search_url or "")
    if not is_linkedin_url(search_url) or not parsed.path.startswith("/jobs/search"):
        parsed = urlsplit(build_jobs_search_url(query or "software engineer"))
    parameters = parse_qs(parsed.query)
    parameters["f_AL"] = ["true"]
    value = normalize_date_range(date_range)
    if value:
        parameters["f_TPR"] = ["r604800" if value == "past_week" else "r86400"]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(parameters, doseq=True), "")
    )


async def prepare_results_page(page, target: str, notify) -> None:
    from src.tools.linkedin_job_selection import read_job_cards

    if await read_job_cards(page):
        return
    if not is_linkedin_url(target) or not urlsplit(target).path.startswith("/jobs/search"):
        raise ValueError("Task 20: no valid filtered search URL for next-job navigation")
    notify("Task 20: returning to the filtered results after closing the rejected application.")
    await page.goto(target)
