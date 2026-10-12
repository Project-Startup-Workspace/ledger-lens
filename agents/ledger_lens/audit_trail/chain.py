"""Hash-chained audit events.

Each event stores the SHA-256 of the previous event, so editing, deleting or reordering
any past event breaks every hash after it. Anyone holding the events can verify the
chain without trusting the system that produced it.
"""

import hashlib
import json
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ledger_lens.shared.pii import mask_value
from ledger_lens.shared.schemas import utc_now

GENESIS = "0" * 64


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
    """Append-only JSON Lines file per case. Used locally and in tests."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(
        self, case_id: str, event_type: str, actor: str, payload: dict[str, Any]
    ) -> AuditEvent:
        with self._lock:
            existing = self.events(case_id)
            event = seal(
                seq=len(existing),
                case_id=case_id,
                event_type=event_type,
                actor=actor,
                at=utc_now(),
                payload=mask_value(payload),
                prev_hash=existing[-1].hash if existing else GENESIS,
            )
            with self._path(case_id).open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
            return event

    def events(self, case_id: str) -> list[AuditEvent]:
        path = self._path(case_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [AuditEvent.model_validate_json(line) for line in lines if line]

    def _path(self, case_id: str) -> Path:
        if not case_id.replace("_", "").isalnum():
            raise ValueError(f"invalid case id {case_id!r}")
        return self._root / f"{case_id}.jsonl"
