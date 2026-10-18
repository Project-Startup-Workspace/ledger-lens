"""Masking of personal data before it reaches logs or audit events.

Covers the identifiers that appear in the target markets: phone numbers, Sri Lankan
NICs, Indian Aadhaar numbers, Singapore NRIC/FINs, Indonesian NIKs and email addresses.
Cloud deployments can add Sensitive Data Protection on top; this module is the floor.
It errs towards over-masking: hiding an amount in a log line is cheaper than leaking an id.
"""

import hashlib
import re
from typing import Any

from pydantic import BaseModel

_PHONE_DIGITS = range(8, 16)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # The TLD must be letters, so versions such as "lk@2026.10.2" are left alone.
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")),
    ("nric", re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)),
    ("nic", re.compile(r"\b\d{9}[VvXx]\b")),
    # New NIC and Aadhaar (12 digits), NIK (16), written solid or in groups of four.
    ("id", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}(?:[\s-]?\d{4})?\b")),
)
# International (+CC ...), trunk-prefixed (0...), Indian mobile (6-9 + 9 digits) and
# Singapore (8/9 + 7 digits) layouts, with optional spaces, dashes or brackets.
_PHONE = re.compile(
    r"(?<![\w+])(?:\+\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,5}){1,4}"
    r"|0\d{1,4}(?:[\s-]?\d{2,5}){1,4}"
    r"|[6-9]\d{9}"
    r"|[89]\d{3}[\s-]\d{4})(?!\w)"
)


def _mask_phone(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group())
    return "[phone]" if digits in _PHONE_DIGITS else match.group()


def mask_text(text: str, known_names: tuple[str, ...] = ()) -> str:
    """Replace personal identifiers and any of `known_names` with placeholders."""
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    text = _PHONE.sub(_mask_phone, text)
    for name in known_names:
        if name.strip():
            text = re.sub(re.escape(name), "[name]", text, flags=re.IGNORECASE)
    return text


def mask_value(value: Any, known_names: tuple[str, ...] = ()) -> Any:
    """Mask strings inside any JSON-like value, including models, dicts and lists."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, str):
        return mask_text(value, known_names)
    if isinstance(value, bool) or value is None or isinstance(value, float):
        return value
    if isinstance(value, int):
        masked = mask_text(str(value), known_names)
        return value if masked == str(value) else masked
    if isinstance(value, dict):
        return {k: mask_value(v, known_names) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [mask_value(v, known_names) for v in value]
    return mask_text(str(value), known_names)


def pseudonym(value: str) -> str:
    """Return a stable, non-reversible token for a value, for joining records without PII."""
    return "p_" + hashlib.sha256(value.strip().lower().encode()).hexdigest()[:16]
