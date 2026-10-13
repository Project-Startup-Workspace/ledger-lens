"""Audit pack: one zip a regulator can verify offline.

Contents: the credit file, the officer report, its hash-chained events, the compliance
reports, the model card, a manifest of SHA-256 hashes, and the lender's Ed25519
signature over the manifest. `verify_pack` checks all of them; given the lender's public key it also
proves the pack came from the lender rather than being rebuilt by someone else.
"""

import base64
import io
import json
import zipfile
import zlib
from typing import Any

from pydantic import BaseModel, ValidationError

from ledger_lens.audit_trail.chain import AuditEvent, canonical_json, sha256_hex, verify_chain
from ledger_lens.audit_trail.signing import Signer, fingerprint, verify_signature
from ledger_lens.shared.schemas import ComplianceReport, CreditFile, utc_now

MANIFEST = "manifest.json"
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
SIGNATURE = "manifest.sig"
PUBLIC_KEY = "signing-key.pub.pem"
EVENTS = "audit_events.jsonl"
# Content files required by each manifest format. Format 1 packs predate the officer
# report; they must keep verifying for as long as they are retained.
FORMAT_VERSION = 2
FORMAT_FILES = {
    1: ("credit_file.json", EVENTS, "compliance.json", "model_card.json", "README.txt"),
    2: (
        "credit_file.json",
        "officer_report.md",
        EVENTS,
        "compliance.json",
        "model_card.json",
        "README.txt",
    ),
}
CONTENT_FILES = FORMAT_FILES[FORMAT_VERSION]
README = """Ledger Lens audit pack

manifest.json lists the SHA-256 of every content file and the head of the event chain.
manifest.sig is the lender's Ed25519 signature over manifest.json.
Each line of audit_events.jsonl holds the hash of the previous event.

Verify with:
  python -m ledger_lens.audit_trail verify <this zip> --public-key <lender key .pem>
"""


class AuditPackError(ValueError):
    """The inputs cannot form a truthful audit pack."""


def build_pack(
    case: CreditFile,
    events: list[AuditEvent],
    compliance: list[ComplianceReport],
    model_card: dict[str, Any] | None,
    officer_report: str,
    signer: Signer,
) -> bytes:
    """Write the signed audit pack zip and return its bytes."""
    if any(event.case_id != case.case_id for event in events):
        raise AuditPackError("events from another case cannot go into this pack")
    chain = verify_chain(events)
    if not chain.valid:
        raise AuditPackError(f"refusing to package a broken chain: {chain.error}")

    files: dict[str, bytes] = {
        "credit_file.json": case.model_dump_json(indent=2).encode(),
        "officer_report.md": officer_report.encode(),
        EVENTS: "".join(e.model_dump_json() + "\n" for e in events).encode(),
        "compliance.json": json.dumps(
            [r.model_dump(mode="json") for r in compliance], indent=2
        ).encode(),
        "model_card.json": json.dumps(model_card or {}, indent=2).encode(),
        "README.txt": README.encode(),
    }
    public_key = signer.public_key_pem()
    manifest = canonical_json(
        {
            "format": FORMAT_VERSION,
            "case_id": case.case_id,
            "generated_at": utc_now().isoformat(),
            "chain": {"events": chain.events, "head": chain.head},
            "rule_packs": sorted({r.rule_pack_version for r in compliance}),
            "model_version": case.risk.model_version if case.risk else None,
            "signing_key": fingerprint(public_key),
            "files": {name: sha256_hex(data) for name, data in sorted(files.items())},
        }
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(MANIFEST, manifest)
        archive.writestr(SIGNATURE, base64.b64encode(signer.sign(manifest)))
        archive.writestr(PUBLIC_KEY, public_key)
    return buffer.getvalue()


class PackVerification(BaseModel):
    valid: bool
    case_id: str | None
    events: int
    signed_by: str | None  # key fingerprint
    key_trusted: bool  # True only when checked against a key supplied by the verifier
    problems: list[str]


def verify_pack(data: bytes, trusted_public_key: bytes | None = None) -> PackVerification:
    """Check signature, required files, every file hash and the whole event chain.

    Without `trusted_public_key` the signature is checked against the key inside the
    pack, which proves integrity but not origin; `key_trusted` is then False.
    """
    try:
        return _verify(data, trusted_public_key)
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError):
        # Corrupt, truncated, encrypted or oddly compressed members: a tampered pack.
        return _invalid("pack is corrupted or not a readable zip file")


def _verify(data: bytes, trusted_public_key: bytes | None) -> PackVerification:
    problems: list[str] = []
    archive = zipfile.ZipFile(io.BytesIO(data))
    with archive:
        # Sizes are declared in the zip directory, so a zip bomb is refused before inflating.
        if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES:
            return _invalid("pack is larger than any genuine audit pack")
        names = set(archive.namelist())
        if missing := [n for n in (MANIFEST, SIGNATURE, PUBLIC_KEY) if n not in names]:
            return _invalid(f"missing files: {', '.join(missing)}")
        manifest_bytes = archive.read(MANIFEST)
        try:
            manifest = json.loads(manifest_bytes)
            listed: dict[str, str] = manifest["files"]
            head = manifest["chain"]["head"]
            case_id = manifest["case_id"]
            required = FORMAT_FILES[manifest.get("format", 1)]
        except (ValueError, KeyError, TypeError, AttributeError):
            return _invalid("manifest is not readable or has an unknown format")
        if not (
            isinstance(listed, dict)
            and all(isinstance(v, str) for v in listed.values())
            and isinstance(head, str)
            and isinstance(case_id, str)
        ):
            return _invalid("manifest fields have the wrong types")
        if missing := [n for n in required if n not in names]:
            return _invalid(f"missing files: {', '.join(missing)}")

        embedded_key = archive.read(PUBLIC_KEY)
        key = trusted_public_key or embedded_key
        signature = archive.read(SIGNATURE).decode(errors="replace")
        if not verify_signature(key, manifest_bytes, signature):
            problems.append("signature does not match the manifest and key")
        if trusted_public_key and fingerprint(trusted_public_key) != fingerprint(embedded_key):
            problems.append("pack was signed with a different key than the trusted one")

        if set(listed) != set(required):
            problems.append("manifest does not list exactly the required content files")
        if extra := names - {MANIFEST, SIGNATURE, PUBLIC_KEY, *required}:
            problems.append(f"unexpected files: {', '.join(sorted(extra))}")
        for name in required:
            if listed.get(name) != sha256_hex(archive.read(name)):
                problems.append(f"{name}: hash does not match the manifest")
        lines = archive.read(EVENTS).decode(errors="replace").splitlines()

    try:
        events = [AuditEvent.model_validate_json(line) for line in lines if line]
    except ValidationError:
        problems.append(f"{EVENTS}: unreadable event")
        events = []
    chain = verify_chain(events)
    if not chain.valid:
        problems.append(f"event chain: {chain.error}")
    elif chain.head != head:
        problems.append("event chain: head differs from the manifest")
    if any(event.case_id != case_id for event in events):
        problems.append("event chain: contains events from another case")
    return PackVerification(
        valid=not problems,
        case_id=case_id,
        events=len(events),
        signed_by=fingerprint(embedded_key),
        key_trusted=trusted_public_key is not None and not problems,
        problems=problems,
    )


def _invalid(problem: str) -> PackVerification:
    return PackVerification(
        valid=False, case_id=None, events=0, signed_by=None, key_trusted=False, problems=[problem]
    )


def snapshot_hash(case: CreditFile) -> str:
    """Hash of the full case at a point in time, for audit events that reference it."""
    return sha256_hex(canonical_json(case.model_dump(mode="json")))
