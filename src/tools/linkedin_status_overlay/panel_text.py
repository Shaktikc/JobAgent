"""Conservative credential redaction and compact text for the public panel.

This guard recognizes obvious shapes; callers must still avoid logging secrets.
Only panel text is transformed. The original CLI message is left untouched.
"""

import re

_CREDENTIAL = re.compile(
    r"\bsk-[A-Za-z0-9_-]+"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]+"
    r"|\b(?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    r"|(?<![\w+/=-])[A-Fa-f0-9]{32,}(?![\w+/=-])"
    r"|(?<![\w+/=-])[A-Za-z0-9_+/=-]{48,}(?![\w+/=-])",
    re.IGNORECASE,
)


def sanitize_panel_text(message: str) -> str:
    """Redact before flattening/truncating, so secrets cannot leak as prefixes."""
    text = " ".join(_CREDENTIAL.sub("[redacted]", message).split())
    return text if len(text) <= 280 else text[:279] + "…"
