"""Audit stores for deployment. The local JSONL store lives in chain.py."""

import random
import re
import time
from typing import Any

from ledger_lens.audit_trail.chain import (
    GENESIS,
    AuditEvent,
    AuditStore,
    JsonlAuditStore,
    seal,
)
from ledger_lens.shared.config import Backend, Settings
from ledger_lens.shared.pii import mask_value
from ledger_lens.shared.schemas import CASE_ID_PATTERN, utc_now

_CASE_ID = re.compile(CASE_ID_PATTERN)
TRANSACTION_ATTEMPTS = 20
_EXHAUSTED = "Failed to commit transaction"  # google-cloud-firestore's retry-exhausted message
APPEND_ROUNDS = 5  # each round retries the whole transaction after a jittered pause


class FirestoreAuditStore:
    """Events in `audit/{case_id}/events/{seq}`; the head is updated in one transaction.

    Two instances appending at once cannot fork the chain: Firestore retries the losing
    transaction, which then sees the new head and appends after it.
    """

    def __init__(self, project: str | None) -> None:
        import google.cloud.firestore as firestore

        self._firestore = firestore
        self._db = firestore.Client(project=project)

    def append(
        self, case_id: str, event_type: str, actor: str, payload: dict[str, Any]
    ) -> AuditEvent:
        from google.api_core.exceptions import Aborted  # cloud extra, imported on use

        if not _CASE_ID.fullmatch(case_id):
            raise ValueError(f"invalid case id {case_id!r}")
        head_ref = self._db.collection("audit").document(case_id)
        firestore = self._firestore

        @firestore.transactional  # type: ignore[untyped-decorator]
        def write(transaction: Any) -> AuditEvent:
            head = head_ref.get(transaction=transaction).to_dict() or {}
            event = seal(
                seq=head.get("seq", -1) + 1,
                case_id=case_id,
                event_type=event_type,
                actor=actor,
                at=utc_now(),
                payload=mask_value(payload),
                prev_hash=head.get("hash", GENESIS),
            )
            events = head_ref.collection("events")
            transaction.create(events.document(f"{event.seq:08d}"), event.model_dump(mode="json"))
            transaction.set(head_ref, {"seq": event.seq, "hash": event.hash})
            return event

        # Under contention Firestore aborts the losing transaction; retrying is safe because
        # each attempt re-reads the head. Giving up would lose an audit event, so try hard.
        for round_no in range(1, APPEND_ROUNDS + 1):
            try:
                result: AuditEvent = write(self._db.transaction(max_attempts=TRANSACTION_ATTEMPTS))
                return result
            except (ValueError, Aborted) as exc:
                # Retry only contention: an aborted read, or the SDK's "every attempt was
                # aborted" error. Anything else fails the same way every time.
                contended = isinstance(exc, Aborted) or str(exc).startswith(_EXHAUSTED)
                if not contended or round_no == APPEND_ROUNDS:
                    raise
                time.sleep(random.uniform(0.05, 0.2) * round_no)  # noqa: S311 - jitter only
        raise AssertionError("unreachable")

    def events(self, case_id: str) -> list[AuditEvent]:
        docs = self._db.collection("audit").document(case_id).collection("events").stream()
        return [
            AuditEvent.model_validate(doc.to_dict()) for doc in sorted(docs, key=lambda d: d.id)
        ]


def build_audit_store(settings: Settings) -> AuditStore:
    if settings.storage_backend is Backend.GCP:
        return FirestoreAuditStore(settings.gcp_project)
    return JsonlAuditStore(settings.data_dir / "audit")
