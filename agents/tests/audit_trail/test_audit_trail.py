"""The audit trail must detect any edit, deletion, reordering, file swap or re-signing."""

import base64
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_lens.audit_trail.chain import JsonlAuditStore, seal, verify_chain
from ledger_lens.audit_trail.pack import AuditPackError, build_pack, snapshot_hash, verify_pack
from ledger_lens.audit_trail.signing import LocalKeySigner
from ledger_lens.risk.model import LogisticModel
from ledger_lens.risk.model_card import model_card
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import Applicant, Consent, CreditFile, LoanRequest

CASE = "case-1"


@pytest.fixture
def store(tmp_path: Path) -> JsonlAuditStore:
    store = JsonlAuditStore(tmp_path / "events")
    for step in ("case_created", "evidence_read", "risk_assessed"):
        store.append(CASE, step, "system", {"step": step})
    return store


@pytest.fixture
def signer(tmp_path: Path) -> LocalKeySigner:
    return LocalKeySigner(tmp_path / "keys" / "lender.pem")


def test_fresh_chain_verifies(store: JsonlAuditStore) -> None:
    result = verify_chain(store.events(CASE))
    assert result.valid and result.events == 3


def test_payloads_are_masked(store: JsonlAuditStore) -> None:
    event = store.append(CASE, "note", "officer-1", {"phone": "0771234567"})
    assert event.payload == {"phone": "[phone]"}


def test_edited_event_is_detected(store: JsonlAuditStore) -> None:
    events = store.events(CASE)
    events[1] = events[1].model_copy(update={"payload": {"step": "forged"}})
    assert verify_chain(events).error == "event 1: altered content"


def test_resealed_edit_breaks_the_next_link(store: JsonlAuditStore) -> None:
    events = store.events(CASE)
    forged = events[1].body() | {"payload": {"step": "forged"}}
    events[1] = seal(**{k: v for k, v in forged.items() if k != "hash"})
    assert verify_chain(events).error == "event 2: broken link"


def test_deleted_or_reordered_events_are_detected(store: JsonlAuditStore) -> None:
    events = store.events(CASE)
    assert not verify_chain([events[0], events[2]]).valid
    assert not verify_chain([events[1], events[0], events[2]]).valid


def test_separate_store_instances_share_one_chain(store: JsonlAuditStore, tmp_path: Path) -> None:
    JsonlAuditStore(tmp_path / "events").append(CASE, "decision", "officer-1", {})
    store.append(CASE, "export", "system", {})
    assert verify_chain(store.events(CASE)).valid


def test_torn_tail_is_quarantined_and_the_chain_continues(
    store: JsonlAuditStore, tmp_path: Path
) -> None:
    path = tmp_path / "events" / f"{CASE}.jsonl"
    with path.open("ab") as fh:
        fh.write(b'{"seq":3,"case_')
    assert len(store.events(CASE)) == 3  # uncommitted line ignored
    event = store.append(CASE, "after_crash", "system", {})
    assert event.seq == 3 and verify_chain(store.events(CASE)).valid
    assert (tmp_path / "events" / f"{CASE}.torn").read_bytes().startswith(b'{"seq":3')


def test_store_rejects_path_like_case_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        JsonlAuditStore(tmp_path).events("../etc")


def make_case(case_id: str = CASE) -> CreditFile:
    return CreditFile(
        case_id=case_id,
        jurisdiction="lk",
        applicant=Applicant(
            full_name="A",
            date_of_birth="1990-01-01",
            national_id="1",
            phone="1",
            business_name="B",
            business_type="shop",
            years_in_business=3,
        ),
        loan=LoanRequest(
            amount=Decimal(1000), currency="LKR", tenor_months=6, annual_rate_pct=20, purpose="x"
        ),
        consent=Consent(given=True),
    )


def members(pack: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


@pytest.fixture
def pack(store: JsonlAuditStore, signer: LocalKeySigner) -> bytes:
    return build_pack(make_case(), store.events(CASE), [], {"version": "v"}, "# report", signer)


def test_pack_verifies_against_the_lender_key(pack: bytes, signer: LocalKeySigner) -> None:
    result = verify_pack(pack, trusted_public_key=signer.public_key_pem())
    assert result.valid and result.key_trusted and result.events == 3 and result.case_id == CASE


def test_swapped_file_is_detected(pack: bytes) -> None:
    forged = members(pack) | {"credit_file.json": b"{}"}
    assert (
        "credit_file.json: hash does not match the manifest" in verify_pack(zipped(forged)).problems
    )


def test_rebuilt_chain_and_manifest_fail_the_signature(pack: bytes) -> None:
    files = members(pack)
    manifest = json.loads(files["manifest.json"])
    del manifest["files"]["credit_file.json"]
    files["manifest.json"] = json.dumps(manifest).encode()
    result = verify_pack(zipped(files))
    assert not result.valid and "signature does not match the manifest and key" in result.problems


def test_pack_resigned_with_another_key_is_not_trusted(
    pack: bytes, signer: LocalKeySigner, tmp_path: Path
) -> None:
    forger = LocalKeySigner(tmp_path / "forger.pem")
    files = members(pack)
    files["manifest.sig"] = base64.b64encode(forger.sign(files["manifest.json"]))
    files["signing-key.pub.pem"] = forger.public_key_pem()
    assert verify_pack(zipped(files)).valid  # self-consistent, so integrity alone passes
    trusted = verify_pack(zipped(files), trusted_public_key=signer.public_key_pem())
    assert not trusted.valid and not trusted.key_trusted


def test_truncated_events_are_detected(pack: bytes) -> None:
    files = members(pack)
    lines = files["audit_events.jsonl"].decode().splitlines()
    files["audit_events.jsonl"] = ("\n".join(lines[:2]) + "\n").encode()
    assert not verify_pack(zipped(files)).valid


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda f: {k: v for k, v in f.items() if k != "audit_events.jsonl"},
        lambda f: f | {"audit_events.jsonl": b"not json\n"},
        lambda f: f | {"manifest.json": b"[]"},
        lambda f: f | {"extra.bin": b"x"},
    ],
)
def test_malformed_packs_are_reported_not_raised(pack: bytes, corrupt) -> None:
    assert not verify_pack(zipped(corrupt(members(pack)))).valid


def test_non_zip_is_reported() -> None:
    assert verify_pack(b"plain text").problems == ["not a zip file"]


def test_build_refuses_other_cases_events_and_broken_chains(
    store: JsonlAuditStore, signer: LocalKeySigner
) -> None:
    events = store.events(CASE)
    with pytest.raises(AuditPackError, match="another case"):
        build_pack(make_case("case-2"), events, [], None, "", signer)
    with pytest.raises(AuditPackError, match="broken chain"):
        build_pack(make_case(), [events[0], events[2]], [], None, "", signer)


def test_snapshot_hash_changes_with_the_case() -> None:
    case = make_case()
    before = snapshot_hash(case)
    case.loan.amount = Decimal(2000)
    assert snapshot_hash(case) != before


def test_model_card_lists_every_feature(settings: Settings) -> None:
    model = LogisticModel.load(settings.risk_model_path)
    card = model_card(model, settings.risk_model_path)
    assert [f["name"] for f in card["features"]] == model.features
    assert card["inventory"]["version"] == model.version
    json.dumps(card)  # must be serialisable into the audit pack


def test_format_1_packs_without_an_officer_report_still_verify(
    store: JsonlAuditStore, signer: LocalKeySigner
) -> None:
    from ledger_lens.audit_trail.chain import canonical_json, sha256_hex

    events = store.events(CASE)
    files = {
        "credit_file.json": b"{}",
        "audit_events.jsonl": "".join(e.model_dump_json() + "\n" for e in events).encode(),
        "compliance.json": b"[]",
        "model_card.json": b"{}",
        "README.txt": b"old pack",
    }
    manifest = canonical_json(
        {
            "case_id": CASE,
            "chain": {"events": 3, "head": events[-1].hash},
            "files": {name: sha256_hex(data) for name, data in files.items()},
        }
    )
    files |= {
        "manifest.json": manifest,
        "manifest.sig": base64.b64encode(signer.sign(manifest)),
        "signing-key.pub.pem": signer.public_key_pem(),
    }
    assert verify_pack(zipped(files), trusted_public_key=signer.public_key_pem()).valid


def test_cloud_storage_requires_a_kms_signing_key(settings: Settings) -> None:
    from ledger_lens.audit_trail.signing import build_signer
    from ledger_lens.shared.config import Backend

    settings.storage_backend = Backend.GCP
    with pytest.raises(ValueError, match="KMS"):
        build_signer(settings)
