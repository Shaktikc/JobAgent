"""Pure, deterministic keyword helpers used by Task 3.1's job profiles.

These helpers do no I/O, no network, and no LLM: they pull known
skills/technologies, significant title words, and seniority out of text. Task 3.1
uses them to build an explainable job profile for judging whether two jobs are
"similar" (so a remembered resume can be reused).

The resume **match** itself is made by the LLM (Task 3.2) — there is no scoring
here anymore.
"""

from __future__ import annotations

import re

# Known skills/technologies that carry matching signal in a job profile.
SKILLS: frozenset[str] = frozenset(
    {
        # languages
        "python",
        "javascript",
        "typescript",
        "java",
        "c#",
        ".net",
        "c++",
        "go",
        "ruby",
        "php",
        "sql",
        "bash",
        # web / frameworks
        "react",
        "node.js",
        "node",
        "django",
        "flask",
        "fastapi",
        "spring",
        "angular",
        "vue",
        "next.js",
        "express",
        # data / ML / AI
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "pandas",
        "numpy",
        "machine learning",
        "deep learning",
        "nlp",
        "llm",
        "rag",
        "langchain",
        "langgraph",
        "openai",
        "transformers",
        "mlops",
        "embeddings",
        "vector database",
        "prompt engineering",
        "agent",
        # cloud / devops
        "aws",
        "azure",
        "gcp",
        "docker",
        "kubernetes",
        "terraform",
        "ci/cd",
        "jenkins",
        "github actions",
        "linux",
        "git",
        # databases
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        # architecture / practices
        "rest",
        "graphql",
        "microservices",
        "api",
        "agile",
    }
)

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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _present(keyword: str, text: str) -> bool:
    """True when ``keyword`` appears in ``text`` as a whole token/phrase."""
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def skills_in_text(text: str) -> list[str]:
    """Return the known skills/technologies present in ``text`` (sorted)."""
    normalized = _normalize(text)
    return sorted(keyword for keyword in SKILLS if _present(keyword, normalized))


def find_seniority(text: str) -> str:
    """Return the highest seniority level mentioned in ``text`` (or ``""``)."""
    normalized = _normalize(text)
    found = [level for level in SENIORITY_LEVELS if _present(level, normalized)]
    return found[-1] if found else ""


def _title_tokens(title: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9+#.]+", _normalize(title))
    return [token for token in tokens if token not in _TITLE_STOPWORDS and len(token) >= 3]


def title_tokens(title: str) -> list[str]:
    """Significant words in a job title (Task 3.1 job profiles)."""
    return _title_tokens(title)


__all__ = ["SENIORITY_LEVELS", "SKILLS", "find_seniority", "skills_in_text", "title_tokens"]
