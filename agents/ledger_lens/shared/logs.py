"""Structured JSON logging with a `case_id` on every line and personal data masked.

One credit file can then be traced across all agents with a single log query.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from ledger_lens.shared.pii import mask_text, mask_value

_case_id: ContextVar[str | None] = ContextVar("case_id", default=None)
_names: ContextVar[tuple[str, ...]] = ContextVar("names", default=())

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line, masking personal data."""

    def format(self, record: logging.LogRecord) -> str:
        names = _names.get()
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": mask_text(record.getMessage(), names),
            "case_id": _case_id.get(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED:
                payload[key] = mask_value(value, names)
        if record.exc_info:
            payload["exception"] = mask_text(self.formatException(record.exc_info), names)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Send JSON logs to stdout, where Cloud Run and local terminals both pick them up."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


@contextmanager
def case_context(case_id: str, names: tuple[str, ...] = ()) -> Iterator[None]:
    """Tag logs inside the block with `case_id` and mask the given personal names."""
    case_token = _case_id.set(case_id)
    names_token = _names.set(names)
    try:
        yield
    finally:
        _case_id.reset(case_token)
        _names.reset(names_token)
