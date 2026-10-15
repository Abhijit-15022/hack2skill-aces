"""Strip secrets and personal identifiers before any text reaches the AI or the database."""
import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:private_key]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api_key]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:api_key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws_key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED:jwt]"),
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED:credentials]@"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api_key|apikey)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{4,}"),
     r"\1\2[REDACTED:password]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED:card_number]"),
    (re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"), "[REDACTED:aadhaar]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[REDACTED:pan]"),
]


def redact(text: str) -> tuple[str, int]:
    """Return the text with secrets replaced by [REDACTED:<kind>] and how many were replaced."""
    if not text:
        return text, 0
    count = 0
    for pattern, repl in _PATTERNS:
        text, n = pattern.subn(repl, text)
        count += n
    return text, count
