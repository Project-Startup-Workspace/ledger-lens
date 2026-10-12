"""Hash-chained audit events.

Each event stores the SHA-256 of the previous event, so editing, deleting or reordering
any past event breaks every hash after it. Anyone holding the events can verify the
chain without trusting the system that produced it.
"""

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ledger_lens.shared.pii import mask_value
from ledger_lens.shared.schemas import utc_now

GENESIS = "0" * 64
_CASE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TAIL_BYTES = 64 * 1024  # events are small; a payload this large is a bug


def canonical_json(value: Any) -> bytes:
    """Stable serialisation: the same value always hashes the same way."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int = Field(ge=0)
    case_id: str
    event_type: str
    actor: str  # "system", an agent name, or an officer id
    at: datetime
    payload: dict[str, Any]  # small, masked summary; never raw personal data
    prev_hash: str
    hash: str

    def body(self) -> dict[str, Any]:
        """Everything the hash covers."""
        return self.model_dump(mode="json", exclude={"hash"})


def seal(**fields: Any) -> AuditEvent:
    """Create an event whose `hash` covers all its other fields."""
    unsealed = {**fields, "hash": ""}
    body = AuditEvent.model_validate(unsealed).body()
    return AuditEvent.model_validate({**body, "hash": sha256_hex(canonical_json(body))})


class ChainVerification(BaseModel):
    valid: bool
    events: int
    head: str
    error: str | None = None


def verify_chain(events: Iterable[AuditEvent]) -> ChainVerification:
    """Recompute every hash and link; report the first break."""
    prev, count = GENESIS, 0
    for count, event in enumerate(events, start=1):
        if event.seq != count - 1:
            return ChainVerification(
                valid=False, events=count, head=prev, error=f"event {count - 1}: wrong sequence"
            )
        if event.prev_hash != prev:
            return ChainVerification(
                valid=False, events=count, head=prev, error=f"event {event.seq}: broken link"
            )
        if sha256_hex(canonical_json(event.body())) != event.hash:
            return ChainVerification(
                valid=False, events=count, head=prev, error=f"event {event.seq}: altered content"
            )
        prev = event.hash
    return ChainVerification(valid=True, events=count, head=prev)


class AuditStore(Protocol):
    def append(
        self, case_id: str, event_type: str, actor: str, payload: dict[str, Any]
    ) -> AuditEvent: ...

    def events(self, case_id: str) -> list[AuditEvent]: ...


class JsonlAuditStore:
    """Append-only JSON Lines file per case, for local use and tests.

    An exclusive file lock serialises appends across threads and processes. Only
    newline-terminated lines count as committed; a torn tail left by a crash is moved
    to a `.torn` file for inspection and the chain continues from the last good event.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def append(
        self, case_id: str, event_type: str, actor: str, payload: dict[str, Any]
    ) -> AuditEvent:
        path = self._path(case_id)
        with path.open("a+b") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                last = self._last_committed(fh, path)
                event = seal(
                    seq=last.seq + 1 if last else 0,
                    case_id=case_id,
                    event_type=event_type,
                    actor=actor,
                    at=utc_now(),
                    payload=mask_value(payload),
                    prev_hash=last.hash if last else GENESIS,
                )
                fh.write(event.model_dump_json().encode() + b"\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return event

    def events(self, case_id: str) -> list[AuditEvent]:
        path = self._path(case_id)
        if not path.exists():
            return []
        data = path.read_bytes()
        committed = data[: data.rfind(b"\n") + 1]
        return [AuditEvent.model_validate_json(line) for line in committed.splitlines() if line]

    def _last_committed(self, fh: BinaryIO, path: Path) -> AuditEvent | None:
        """Read only the final committed line, truncating any torn tail first."""
        size = fh.seek(0, os.SEEK_END)
        if size == 0:
            return None
        fh.seek(max(0, size - _TAIL_BYTES))
        tail = fh.read()
        end = tail.rfind(b"\n")
        if end != len(tail) - 1:  # torn write: keep it aside, never in the chain
            torn = tail[end + 1 :]
            with path.with_suffix(".torn").open("ab") as quarantine:
                quarantine.write(torn + b"\n")
            fh.truncate(size - len(torn))
            tail = tail[: end + 1]
        if not tail.strip():
            return None
        start = tail.rfind(b"\n", 0, len(tail) - 1) + 1
        if start == 0 and size > _TAIL_BYTES:
            raise ValueError(f"last audit event in {path.name} exceeds {_TAIL_BYTES} bytes")
        return AuditEvent.model_validate_json(tail[start:])

    def _path(self, case_id: str) -> Path:
        if not _CASE_ID.fullmatch(case_id):
            raise ValueError(f"invalid case id {case_id!r}")
        return self._root / f"{case_id}.jsonl"
