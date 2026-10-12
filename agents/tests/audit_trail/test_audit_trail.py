"""The audit trail must detect any edit, deletion, reordering or file swap."""

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_lens.audit_trail.chain import JsonlAuditStore, seal, verify_chain
from ledger_lens.audit_trail.pack import build_pack, snapshot_hash, verify_pack
from ledger_lens.risk.model import LogisticModel
from ledger_lens.risk.model_card import model_card
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import Applicant, Consent, CreditFile, LoanRequest


@pytest.fixture
def store(tmp_path: Path) -> JsonlAuditStore:
    store = JsonlAuditStore(tmp_path)
    for step in ("case_created", "evidence_read", "risk_assessed"):
        store.append("case_1", step, "system", {"step": step})
    return store


def test_fresh_chain_verifies(store: JsonlAuditStore) -> None:
    result = verify_chain(store.events("case_1"))
    assert result.valid and result.events == 3


def test_payloads_are_masked(store: JsonlAuditStore) -> None:
    event = store.append("case_1", "note", "officer-1", {"phone": "0771234567"})
    assert event.payload == {"phone": "[phone]"}


def test_edited_event_is_detected(store: JsonlAuditStore) -> None:
    events = store.events("case_1")
    events[1] = events[1].model_copy(update={"payload": {"step": "forged"}})
    assert verify_chain(events).error == "event 1: altered content"


def test_resealed_edit_breaks_the_next_link(store: JsonlAuditStore) -> None:
    events = store.events("case_1")
    forged = events[1].body() | {"payload": {"step": "forged"}}
    events[1] = seal(**{k: v for k, v in forged.items() if k != "hash"})
    assert verify_chain(events).error == "event 2: broken link"


def test_deleted_or_reordered_events_are_detected(store: JsonlAuditStore) -> None:
    events = store.events("case_1")
    assert not verify_chain([events[0], events[2]]).valid
    assert not verify_chain([events[1], events[0], events[2]]).valid


def test_store_rejects_path_like_case_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        JsonlAuditStore(tmp_path).events("../etc")


def make_case() -> CreditFile:
    return CreditFile(
        case_id="case_1",
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


def rewrite(pack: bytes, name: str, data: bytes) -> bytes:
    """Copy a zip, replacing one member."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(pack)) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.namelist():
            dst.writestr(item, data if item == name else src.read(item))
    return out.getvalue()


def test_audit_pack_round_trip_and_tamper_detection(store: JsonlAuditStore) -> None:
    pack = build_pack(make_case(), store.events("case_1"), [], {"version": "v"})
    result = verify_pack(pack)
    assert result.valid and result.events == 3 and result.case_id == "case_1"

    forged_case = rewrite(pack, "credit_file.json", b"{}")
    assert "credit_file.json: hash does not match the manifest" in verify_pack(forged_case).problems

    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        lines = archive.read("audit_events.jsonl").decode().splitlines()
    truncated = rewrite(pack, "audit_events.jsonl", ("\n".join(lines[:2]) + "\n").encode())
    assert not verify_pack(truncated).valid


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
