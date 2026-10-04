"""Pure, deterministic resume-to-job matching (no I/O, no network, no LLM).

The score is an explainable weighted sum of:

- **skills/technologies** the job description and the resume share,
- **title** keyword overlap,
- **seniority** match,
- **years of experience** fit (required vs. mentioned).

Every contribution is recorded in :class:`MatchResult` so the chosen resume can
be justified in the run log. Callers compare scores across resumes; ties are
broken by the caller using file modification time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Weighted skills/technologies. Higher weight = a more decisive signal.
SKILL_WEIGHTS: dict[str, float] = {
    # languages
    "python": 3.0,
    "javascript": 2.0,
    "typescript": 2.0,
    "java": 2.0,
    "c#": 3.0,
    ".net": 3.0,
    "c++": 2.0,
    "go": 2.0,
    "ruby": 1.0,
    "php": 1.0,
    "sql": 2.0,
    "bash": 1.0,
    # web / frameworks
    "react": 2.0,
    "node.js": 2.0,
    "node": 2.0,
    "django": 2.0,
    "flask": 2.0,
    "fastapi": 2.0,
    "spring": 2.0,
    "angular": 2.0,
    "vue": 1.0,
    "next.js": 1.5,
    "express": 1.0,
    # data / ML / AI
    "pytorch": 2.0,
    "tensorflow": 2.0,
    "scikit-learn": 2.0,
    "pandas": 1.0,
    "numpy": 1.0,
    "machine learning": 3.0,
    "deep learning": 2.0,
    "nlp": 2.0,
    "llm": 3.0,
    "rag": 3.0,
    "langchain": 3.0,
    "langgraph": 3.0,
    "openai": 2.0,
    "transformers": 2.0,
    "mlops": 2.0,
    "embeddings": 2.0,
    "vector database": 2.0,
    "prompt engineering": 2.0,
    "agent": 2.0,
    # cloud / devops
    "aws": 2.0,
    "azure": 2.0,
    "gcp": 2.0,
    "docker": 2.0,
    "kubernetes": 2.0,
    "terraform": 1.0,
    "ci/cd": 1.0,
    "jenkins": 1.0,
    "github actions": 1.0,
    "linux": 1.0,
    "git": 1.0,
    # databases
    "postgresql": 1.0,
    "mysql": 1.0,
    "mongodb": 1.0,
    "redis": 1.0,
    "elasticsearch": 1.0,
    # architecture / practices
    "rest": 1.0,
    "graphql": 1.0,
    "microservices": 2.0,
    "api": 1.0,
    "agile": 1.0,
}

# Seniority levels, listed from low to high.
SENIORITY_LEVELS = (
    "intern",
    "junior",
    "mid",
    "senior",
    "staff",
    "lead",
    "principal",
    "manager",
    "director",
)

# Words that carry no matching signal when they appear in a job title.
_TITLE_STOPWORDS = frozenset(
    {"the", "and", "or", "of", "for", "a", "an", "with", "to", "in", "at", "on", "as"}
)

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", re.IGNORECASE)


@dataclass(frozen=True)
class MatchResult:
    """The explainable outcome of scoring one resume against one job."""

    score: float
    matched_skills: tuple[str, ...] = ()
    title_hits: tuple[str, ...] = ()
    seniority: str = ""
    seniority_matched: bool = False
    required_years: int | None = None
    resume_years: int | None = None
    rationale: str = ""
    components: dict[str, float] = field(default_factory=dict)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _present(keyword: str, text: str) -> bool:
    """True when ``keyword`` appears in ``text`` as a whole token/phrase."""
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def skills_in_text(text: str) -> list[str]:
    """Return the known skills/technologies present in ``text`` (sorted)."""
    normalized = _normalize(text)
    return sorted(keyword for keyword in SKILL_WEIGHTS if _present(keyword, normalized))


def find_seniority(text: str) -> str:
    """Return the highest seniority level mentioned in ``text`` (or ``""``)."""
    normalized = _normalize(text)
    found = [level for level in SENIORITY_LEVELS if _present(level, normalized)]
    return found[-1] if found else ""


def _max_years(text: str) -> int | None:
    matches = [int(value) for value in _YEARS_RE.findall(text)]
    return max(matches) if matches else None


def _title_tokens(title: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9+#.]+", _normalize(title))
    return [token for token in tokens if token not in _TITLE_STOPWORDS and len(token) >= 3]


def _build_rationale(
    matched: list[str],
    title_hits: list[str],
    seniority: str,
    seniority_matched: bool,
    required_years: int | None,
    resume_years: int | None,
) -> str:
    parts: list[str] = []
    if matched:
        parts.append("shared skills: " + ", ".join(matched))
    else:
        parts.append("no shared skills")

    if title_hits:
        parts.append("title overlap: " + ", ".join(title_hits))

    if seniority:
        verdict = "matched" if seniority_matched else "not shown"
        parts.append(f"seniority '{seniority}' {verdict}")

    if required_years is not None:
        if resume_years is None:
            parts.append(f"requires {required_years}+ years (not stated in resume)")
        else:
            parts.append(f"{resume_years} years vs {required_years}+ required")

    return "; ".join(parts)


def score_resume(job_title: str, job_text: str, resume_text: str) -> MatchResult:
    """Score ``resume_text`` against a job and explain the score.

    ``job_title`` is passed separately from ``job_text`` so title overlap is not
    inflated by the description body.
    """
    job = _normalize(job_text)
    resume = _normalize(resume_text)

    job_skills = skills_in_text(job)
    resume_skills = set(skills_in_text(resume))
    matched = [keyword for keyword in job_skills if keyword in resume_skills]
    skill_score = sum(SKILL_WEIGHTS[keyword] for keyword in matched)

    title_hits = [token for token in _title_tokens(job_title) if _present(token, resume)]
    title_score = 2.0 * len(title_hits)

    seniority = find_seniority(job_title) or find_seniority(job)
    seniority_matched = bool(seniority) and _present(seniority, resume)
    seniority_score = 3.0 if seniority_matched else 0.0

    required_years = _max_years(job)
    resume_years = _max_years(resume)
    if required_years and resume_years:
        experience_score = 3.0 * min(resume_years / required_years, 1.0)
    else:
        experience_score = 0.0

    components = {
        "skills": round(skill_score, 2),
        "title": round(title_score, 2),
        "seniority": round(seniority_score, 2),
        "experience": round(experience_score, 2),
    }
    rationale = _build_rationale(
        matched, title_hits, seniority, seniority_matched, required_years, resume_years
    )
    return MatchResult(
        score=round(sum(components.values()), 2),
        matched_skills=tuple(matched),
        title_hits=tuple(title_hits),
        seniority=seniority,
        seniority_matched=seniority_matched,
        required_years=required_years,
        resume_years=resume_years,
        rationale=rationale,
        components=components,
    )
