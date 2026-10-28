"""Task 3.1: read the open job's title, company, location, and description.

This is a deterministic CDP ``page.evaluate`` (no LLM). LinkedIn serves several
layouts for the same job: the classic two-pane results page, a newer full-page
view, and an AI/semantic view with hashed CSS-in-JS class names. The selectors
are tried inside the job-details pane first; a class-agnostic paragraph fallback
covers the hashed layout.

The title lookup is **scoped to the job pane**. A previous global ``h1``/``h2``
fallback matched LinkedIn's own chrome, so a Full Stack Engineer job was logged
as ``'0 notifications'`` and the LLM matched against that meaningless title.
Only the pane's headings, the page title, and job-specific class names are used.
"""

from __future__ import annotations

from src.state import JobDescription
from src.tools.browser import _loads, _safe

_JOB_DESCRIPTION_QUERY = r"""
() => {
  const clean = (text) => (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const textOf = (el) => (el ? clean(el.innerText) : '');
  const firstIn = (scope, selectors, minimum) => {
    if (!scope) return '';
    for (const selector of selectors) {
      let el = null;
      try { el = scope.querySelector(selector); } catch (err) { continue; }
      const text = textOf(el);
      if (text.length >= (minimum || 1)) return text;
    }
    return '';
  };
  const first = (selectors, minimum) => firstIn(document, selectors, minimum);
  const detailsRoot = () => {
    const roots = [
      'div.jobs-search__job-details--container',
      'div.scaffold-layout__detail',
      'div.job-view-layout',
      'section.jobs-details',
      'div.jobs-details',
      'main',
      '[role="main"]'
    ];
    for (const selector of roots) {
      let el = null;
      try { el = document.querySelector(selector); } catch (err) { continue; }
      if (el && clean(el.innerText)) return el;
    }
    return document.body;
  };
  // Class-agnostic fallback: job descriptions are paragraph/list based, so read
  // every paragraph/li under the details pane. This survives LinkedIn's hashed
  // CSS-in-JS class names (the AI/semantic job view).
  const paragraphText = (root) => {
    if (!root) return '';
    const parts = [];
    const seen = new Set();
    for (const el of root.querySelectorAll('p, li')) {
      const text = clean(el.innerText);
      if (text.length < 20 || text.length > 4000 || seen.has(text)) continue;
      seen.add(text);
      parts.push(text);
    }
    return parts.join('\n');
  };
  // The AI/search view has an "About the job" heading; read the page text after
  // it (LinkedIn renders the description there) instead of every paragraph in
  // the page's main area, which also holds the job list (BUG-072).
  const aboutText = () => {
    const heading = Array.from(document.querySelectorAll('h1,h2,h3,h4'))
      .filter((el) => el.getClientRects().length > 0)
      .find((el) => /^about the job$/i.test(clean(el.innerText)));
    if (!heading) return '';
    const root = document.querySelector('main, [role="main"]') || document.body;
    const full = clean(root.innerText);
    const marker = clean(heading.innerText);
    const index = full.indexOf(marker);
    if (index < 0) return '';
    return full.slice(index + marker.length).trim();
  };
  const bodyAfterHeading = (pattern) => {
    const heading = Array.from(document.querySelectorAll('h1,h2,h3,h4'))
      .filter((el) => el.getClientRects().length > 0)
      .find((el) => pattern.test(clean(el.innerText)));
    if (!heading) return '';
    const parts = [];
    for (let node = heading.nextElementSibling; node; node = node.nextElementSibling) {
      if (/^h[1-6]$/i.test(node.tagName)) break;
      const text = clean(node.innerText);
      if (text) parts.push(text);
    }
    return parts.join('\n');
  };
  // LinkedIn's global navigation exposes headings such as "0 notifications".
  // They are never a job title, and using one made the resume match meaningless.
  const chromeCount = /^(?:\(\d+\)\s*)?(?:\d+\s+)?(?:new\s+)?notifications?$/i;
  const chromeNav = /^(?:home|my network|jobs|messaging|linkedin|for business)$/i;
  const chromeNoise = new RegExp(
    '^(?:are these results helpful.*|about the job|get job alerts.*|'
    + 'see jobs where.*|your feedback helps.*)$', 'i');
  const plausibleTitle = (value) => {
    const text = clean(value);
    if (!text || chromeCount.test(text) || chromeNav.test(text) || chromeNoise.test(text)) {
      return '';
    }
    return text;
  };
  // The tab title is often "Job title | Company | LinkedIn" on the AI/semantic
  // job view. Parse it before any generic heading: a survey heading such as
  // "Are these results helpful?" is not a job title (BUG-072).
  const documentMeta = () => {
    const parts = clean(document.title)
      .replace(/\s*\|\s*LinkedIn\s*$/i, '')
      .replace(/^\(\d+\)\s*/, '')
      .split('|')
      .map(clean)
      .filter(Boolean);
    const companyText = parts.length > 1 ? parts[parts.length - 1] : '';
    return {
      title: plausibleTitle(parts[0] || ''),
      company: companyText && !chromeNoise.test(companyText) ? companyText : ''
    };
  };
  const meta = documentMeta();
  const documentTitle = () => meta.title;

  const root = detailsRoot();
  const scoped = root && root !== document.body ? root : null;
  const titleSelectors = [
    '.job-details-jobs-unified-top-card__job-title',
    '.jobs-unified-top-card__job-title',
    '.top-card-layout__title',
    '.topcard__title',
    'h1.t-24',
    '[class*="job-title"]'
  ];
  const aboutBody = bodyAfterHeading(/^about the job$/i);
  const about = aboutText();
  let title = plausibleTitle(firstIn(scoped, titleSelectors));
  if (!title) {
    // Prefer the tab title over generic pane headings: the AI/search view puts
    // survey headings ("Are these results helpful?") before the job title.
    title = documentTitle();
  }
  if (!title) {
    title = plausibleTitle(firstIn(scoped, ['h1', 'h2']));
  }
  if (!title) {
    title = plausibleTitle(firstIn(document, ['[class*="job-title"]']));
  }

  const company = firstIn(scoped, [
    '.job-details-jobs-unified-top-card__company-name',
    '.jobs-unified-top-card__company-name',
    '.topcard__org-name-link',
    'a.topcard__org-name-link',
    '[class*="company-name"]'
  ]) || first([
    '.job-details-jobs-unified-top-card__company-name',
    '.jobs-unified-top-card__company-name',
    '.topcard__org-name-link',
    'a.topcard__org-name-link',
    '[class*="company-name"]'
  ]) || meta.company;
  const locationText = firstIn(scoped, [
    '.job-details-jobs-unified-top-card__bullet',
    '.jobs-unified-top-card__bullet',
    '.topcard__flavor--bullet'
  ]) || first([
    '.job-details-jobs-unified-top-card__bullet',
    '.jobs-unified-top-card__bullet',
    '.topcard__flavor--bullet'
  ]);
  let body =
    firstIn(scoped, [
      '.jobs-description__content',
      '.jobs-box__html-content',
      '#job-details',
      '.jobs-description'
    ]) ||
    firstIn(scoped, ['.description__text', '.show-more-less-html__markup']) ||
    firstIn(scoped, ['[class*="description"]'], 200) ||
    firstIn(document, ['.description__text', '.show-more-less-html__markup']) ||
    (about.length >= 200 ? about : '') ||
    (aboutBody.length >= 200 ? aboutBody : '') ||
    paragraphText(root);
  // On the AI/search landing view the paragraph fallback reads the whole main
  // area (job list + survey + description). Start at the actual job title when it
  // appears, and stop before LinkedIn's Premium footer, so the stored description
  // is the job's text rather than the page chrome (BUG-072).
  if (title && body.length > 800) {
    const first = body.indexOf(title);
    const second = first >= 0 ? body.indexOf(title, first + title.length) : -1;
    const start = second > 0 ? second : first;
    if (start > 0) body = body.slice(start);
  }
  const premium = body.search(/Job search faster with Premium/i);
  if (premium > 0) body = body.slice(0, premium);
  return JSON.stringify({
    title: title,
    company: company,
    location: locationText,
    body: body,
    url: location.href
  });
}
"""


async def read_job_description(page) -> JobDescription:
    """Read the open job's title, company, location, and description (Task 3)."""
    payload = _loads(await _safe(page.evaluate(_JOB_DESCRIPTION_QUERY), ""))
    return JobDescription(
        title=(payload.get("title") or "").strip(),
        company=(payload.get("company") or "").strip(),
        location=(payload.get("location") or "").strip(),
        body=(payload.get("body") or "").strip(),
        page_url=payload.get("url") or None,
    )


__all__ = ["_JOB_DESCRIPTION_QUERY", "read_job_description"]
