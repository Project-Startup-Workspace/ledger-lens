"""Audit pack: one zip a regulator can verify offline.

Contents: the credit file, its hash-chained events, the compliance reports, the model
card and a manifest of SHA-256 hashes. `verify_pack` checks all of them.
"""

import io
import json
import zipfile
from typing import Any

from pydantic import BaseModel

from ledger_lens.audit_trail.chain import (
    AuditEvent,
    canonical_json,
    sha256_hex,
    verify_chain,
)
from ledger_lens.shared.schemas import ComplianceReport, CreditFile, utc_now

MANIFEST = "manifest.json"
README = """Ledger Lens audit pack

manifest.json lists the SHA-256 of every other file and the head of the event chain.
Each line of audit_events.jsonl holds the hash of the previous event.

Verify with:  python -m ledger_lens.audit_trail verify <this zip>
"""


def build_pack(
    case: CreditFile,
    events: list[AuditEvent],
    compliance: list[ComplianceReport],
    model_card: dict[str, Any] | None,
) -> bytes:
    """Write the audit pack zip and return its bytes."""
    chain = verify_chain(events)
    files: dict[str, bytes] = {
        "credit_file.json": case.model_dump_json(indent=2).encode(),
        "audit_events.jsonl": "".join(e.model_dump_json() + "\n" for e in events).encode(),
        "compliance.json": json.dumps(
            [r.model_dump(mode="json") for r in compliance], indent=2
        ).encode(),
        "model_card.json": json.dumps(model_card or {}, indent=2).encode(),
        "README.txt": README.encode(),
    }
    manifest = {
        "case_id": case.case_id,
        "generated_at": utc_now().isoformat(),
        "chain": {"events": chain.events, "head": chain.head, "valid": chain.valid},
        "rule_packs": sorted({r.rule_pack_version for r in compliance}),
        "model_version": case.risk.model_version if case.risk else None,
        "files": {name: sha256_hex(data) for name, data in sorted(files.items())},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
    return buffer.getvalue()


class PackVerification(BaseModel):
    valid: bool
    case_id: str | None
    events: int
    problems: list[str]


def verify_pack(data: bytes) -> PackVerification:
    """Check every file hash in the manifest and the whole event chain."""
    problems: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        for name, expected in manifest["files"].items():
            try:
                actual = sha256_hex(archive.read(name))
            except KeyError:
                problems.append(f"{name}: missing")
                continue
            if actual != expected:
                problems.append(f"{name}: hash does not match the manifest")
        lines = archive.read("audit_events.jsonl").decode().splitlines()
    events = [AuditEvent.model_validate_json(line) for line in lines if line]
    chain = verify_chain(events)
    if not chain.valid:
        problems.append(f"event chain: {chain.error}")
    elif chain.head != manifest["chain"]["head"]:
        problems.append("event chain: head differs from the manifest (events added or removed)")
    return PackVerification(
        valid=not problems, case_id=manifest.get("case_id"), events=len(events), problems=problems
    )


def snapshot_hash(case: CreditFile) -> str:
    """Hash of the full case at a point in time, for audit events that reference it."""
    return sha256_hex(canonical_json(case.model_dump(mode="json")))
