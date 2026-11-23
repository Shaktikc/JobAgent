"""Unique job evaluations and confirmed submissions within one session."""
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class ApplicationCounts:
    scanned_jobs: set[str] = field(default_factory=set)
    submitted_jobs: set[str] = field(default_factory=set)
    current: str = ''

    @property
    def scanned(self):
        return len(self.scanned_jobs)

    @property
    def submitted(self):
        return len(self.submitted_jobs)

    def scan(self, key):
        self.current = key
        self.scanned_jobs.add(key)

    def confirm(self):
        if self.current:
            self.submitted_jobs.add(self.current)

    def format(self):
        return f'Scanned: {self.scanned:,} | Submitted: {self.submitted:,}'


async def record_scan(page, card, fallback_key):
    """Prefer LinkedIn's stable job ID; scope fallback keys to the result page."""
    from src.tools.linkedin_validation.identity import read_card_id

    from . import runtime

    identity = await read_card_id(card)
    if identity:
        key = f'job:{identity}'
    else:
        try:
            url = urlsplit(await page.get_url() or '')
            query = [(k, v) for k, v in parse_qsl(url.query)
                     if k not in ('currentJobId', 'jobId', 'trackingId', 'refId')]
            location = urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ''))
        except Exception:
            location = ''
        key = f'{location}|{fallback_key}'
    runtime.applications.scan(key)
    runtime.publish()
