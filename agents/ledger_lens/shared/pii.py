"""Masking of personal data before it reaches logs or audit events.

Covers the identifiers that appear in demo markets: phone numbers, Sri Lankan NICs,
Indian Aadhaar numbers, Singapore NRIC/FINs, Indonesian NIKs and email addresses.
Cloud deployments can add Sensitive Data Protection on top; this module is the floor.
"""

import hashlib
import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("nric", re.compile(r"\b[STFGM]\d{7}[A-Z]\b")),
    ("nic", re.compile(r"\b\d{9}[VvXx]\b")),
    ("id", re.compile(r"\b\d{12}(?:\d{4})?\b")),  # new NIC, Aadhaar (12) and NIK (16)
    # Phone numbers start with + or 0 so plain amounts such as 125000 are left alone.
    ("phone", re.compile(r"(?<![\w])(?:\+\d{1,3}[\s-]?|0)\d{2}[\s-]?\d{3}[\s-]?\d{3,4}\b")),
)


def mask_text(text: str, known_names: tuple[str, ...] = ()) -> str:
    """Replace personal identifiers and any of `known_names` with placeholders."""
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    for name in known_names:
        if name.strip():
            text = re.sub(re.escape(name), "[name]", text, flags=re.IGNORECASE)
    return text


def pseudonym(value: str) -> str:
    """Return a stable, non-reversible token for a value, for joining records without PII."""
    return "p_" + hashlib.sha256(value.strip().lower().encode()).hexdigest()[:16]
