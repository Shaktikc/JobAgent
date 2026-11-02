"""Resolve a posting's canonical link without confusing identical job titles."""

import re
from urllib.parse import parse_qs, urlsplit

from src.tools.browser import _safe


def job_id_from_url(url: str) -> str:
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return ""
    match = re.search(r"/jobs/view/(\d+)(?:/|$)", parsed.path)
    if match:
        return match[1]
    query = parse_qs(parsed.query)
    for key in ("currentJobId", "jobId"):
        value = next(iter(query.get(key, [])), "")
        if value.isdigit():
            return value
    return ""


_CARD_ID = r"""() => {
  const nodes = [this, ...this.querySelectorAll(
    '[data-job-id],[data-occludable-job-id],[data-entity-urn],[componentkey],a[href*="/jobs/view/"]')];
  for (const node of nodes) {
    const attributes = [
      'data-job-id','data-occludable-job-id','data-entity-urn','componentkey','href'];
    for (const attr of attributes) {
      const value = node.getAttribute(attr) || '';
      const match = value.match(/^\d+$/)
        || value.match(/(?:jobPosting:|job-card-component-ref-|\/jobs\/view\/)(\d+)/);
      if (match) return match[1] || match[0];
    }
  }
  return '';
}"""


async def read_card_id(card) -> str:
    value = str(await _safe(card.evaluate(_CARD_ID), "") or "")
    return value if value.isdigit() else ""


async def current_job_link(page, state) -> tuple[str, str]:
    """Prefer the live selected job; never persist just the search-results URL."""
    task2 = state.get("task2")
    description = state.get("job_description")
    urls = [
        await _safe(page.get_url(), ""),
        task2.page_url if task2 else "",
        description.page_url if description else "",
    ]
    for url in urls:
        identity = job_id_from_url(url or "")
        if identity:
            return identity, f"https://www.linkedin.com/jobs/view/{identity}/"
    # A canonical/share link belongs to the details pane; do not borrow the
    # first posting anchor from the results list.
    url = await _safe(
        page.evaluate("""() => {
      const link = document.querySelector('.jobs-details a[href*="/jobs/view/"],'
        + '.job-details-jobs-unified-top-card__job-title a[href*="/jobs/view/"],'
        + 'link[rel="canonical"][href*="/jobs/view/"]');
      return link ? link.href : '';
    }"""),
        "",
    )
    identity = job_id_from_url(url or "")
    return (identity, f"https://www.linkedin.com/jobs/view/{identity}/") if identity else ("", "")
