"""Regression tests for the full-codebase review of the Phase 1 release."""

import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ledger_lens.a2a_server import handle
from ledger_lens.api.app import create_app
from ledger_lens.audit_trail.chain import sha256_hex
from ledger_lens.audit_trail.pack import verify_pack
from ledger_lens.consistency.tools import compare, weekly_series
from ledger_lens.coordinator import Coordinator, build_services
from ledger_lens.demo import open_demo_case
from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.evidence.schemas import WireEntry, WireExtraction
from ledger_lens.risk.model import LogisticModel
from ledger_lens.risk.model_card import model_card
from ledger_lens.shared.config import Settings
from ledger_lens.shared.governance import bias_report_path, model_record
from ledger_lens.shared.safety import HeuristicScreen
from ledger_lens.shared.schemas import (
    Applicant,
    Direction,
    EvidenceDocument,
    EvidenceKind,
    LedgerEntry,
    LoanRequest,
)
from tests.conftest import DEMO


@pytest.fixture
def coordinator(settings: Settings) -> Coordinator:
    return Coordinator(build_services(settings))


def test_decision_reason_hash_matches_the_stored_reason(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    coordinator.assess(case.case_id)
    decided = coordinator.decide(
        case.case_id, officer_id="o", outcome="approve", reason="  Steady sales\n"
    )
    event = coordinator.audit_events(case.case_id)[-2]  # decision, then compliance
    assert event.event_type == "decision_recorded"
    assert event.payload["reason_sha256"] == sha256_hex(decided.decision.reason.encode())  # type: ignore[union-attr]


def test_entries_after_case_creation_are_read(coordinator: Coordinator, settings: Settings) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    stored = coordinator.get(case.case_id)
    stored.created_at = stored.created_at.replace(year=2026, month=8, day=1)  # before the entries
    build_services(settings).cases.save(stored)
    assessed = coordinator.assess(case.case_id)
    assert assessed.cash_flow and assessed.cash_flow.weeks_covered == 8


def test_acknowledgement_survives_a_reassessment(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    coordinator.assess(case.case_id)
    acknowledged = coordinator.acknowledge_disclosure(case.case_id, blank_fields=[], actor="o")
    again = coordinator.assess(case.case_id)
    assert again.disclosure and again.disclosure.acknowledged_at
    assert again.disclosure.acknowledged_at == acknowledged.disclosure.acknowledged_at  # type: ignore[union-attr]


def test_audit_pack_carries_the_card_of_the_model_that_scored_the_case(
    settings: Settings, tmp_path: Path
) -> None:
    active = tmp_path / "active.json"
    active.write_text(settings.risk_model_path.read_text())
    settings.risk_model_path = active
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    coordinator.assess(case.case_id)
    original = json.loads(active.read_text())
    (tmp_path / f"{original['version']}.json").write_text(active.read_text())
    active.write_text(json.dumps(original | {"version": "risk-v2"}))  # a new model goes live

    pack = coordinator.export_audit_pack(case.case_id, "o")
    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        card = json.loads(archive.read("model_card.json"))
    assert card["inventory"]["version"] == original["version"]


def test_model_card_marks_a_stale_bias_report(settings: Settings, tmp_path: Path) -> None:
    artifact = tmp_path / "m.json"
    artifact.write_text(settings.risk_model_path.read_text())
    bias_report_path(artifact).write_text(
        '{"passes_four_fifths": true, "model_fingerprint": "old"}'
    )
    card = model_card(LogisticModel.load(artifact), artifact)
    assert card["fairness"]["valid_for_this_artifact"] is False


def test_model_versions_cannot_point_outside_the_artifacts(settings: Settings) -> None:
    record = model_record(settings.risk_model_path, "../../../../etc/passwd")
    assert record and record.validation_auc is None and not record.bias_report


def test_risk_scoring_cannot_overflow(settings: Settings) -> None:
    model = LogisticModel.load(settings.risk_model_path)
    extreme = dict.fromkeys(model.features, 1e6)
    assert 0.0 <= model.probability(extreme) <= 1.0
    with pytest.raises(ValidationError):
        Applicant(
            full_name="A",
            date_of_birth="1990-01-01",
            national_id="1",
            phone="1",
            business_name="B",
            business_type="shop",
            years_in_business=100_000,
        )


def test_currency_codes_are_normalised_once() -> None:
    loan = LoanRequest(
        amount=Decimal(1), currency="lkr", tenor_months=1, annual_rate_pct=1, purpose="x"
    )
    assert loan.currency == "LKR"
    with pytest.raises(ValidationError):
        LoanRequest(
            amount=Decimal(1), currency="rupees", tenor_months=1, annual_rate_pct=1, purpose="x"
        )


def test_implausible_model_amounts_are_skipped_not_fatal(settings: Settings) -> None:
    def line(amount: float, confidence: float = 0.9) -> WireEntry:
        return WireEntry(
            date="2026-09-01",
            description="sale",
            amount=amount,
            direction="in",
            confidence=confidence,
            box_2d=[0, 0, 10, 10],
            raw_text=str(amount),
        )

    class Stub:
        def generate(self, **_: object) -> WireExtraction:
            return WireExtraction(
                script="Latin",
                language="en",
                currency="LKR",
                entries=[line(100), line(float("nan")), line(1e30), line(5, float("nan"))],
                other_text="",
                warnings=[],
            )

        def speak(self, **_: object) -> bytes:
            raise NotImplementedError

    doc = EvidenceDocument(
        kind=EvidenceKind.NOTEBOOK,
        filename="p.png",
        content_type="image/png",
        sha256="-",
        blob_key="k",
    )
    result = EvidenceAgent(Stub(), HeuristicScreen(), settings).read(  # type: ignore[arg-type]
        doc, b"img", reference_date=__import__("datetime").date(2026, 10, 12), currency="LKR"
    )
    assert [e.amount for e in result.entries] == [Decimal("100.00")]
    assert sum("Skipped" in w for w in result.warnings) == 3


def test_unreadable_wallet_weeks_are_skipped_not_flagged() -> None:
    from datetime import date

    def daily(weekly: list[int], unreadable_week: int | None = None) -> list[LedgerEntry]:
        entries = []
        start = date(2026, 8, 10)
        for week, total in enumerate(weekly):
            for day in range(7):
                entries.append(
                    LedgerEntry(
                        evidence_id="ev",
                        entry_date=start + timedelta(weeks=week, days=day),
                        description="x",
                        amount=Decimal(total) / 7,
                        direction=Direction.IN,
                        confidence=0.3 if week == unreadable_week and day == 0 else 1.0,
                    )
                )
        return entries

    notebook = weekly_series(daily([100] * 6), 0.6)
    wallet = weekly_series(daily([50] * 6, unreadable_week=3), 0.6)
    report = compare(notebook, wallet, 0.35, "LKR")
    assert report.flags == [] and report.weeks_compared == 5


def test_naive_timestamps_in_a2a_requests_get_an_error_reply(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o").model_dump(mode="json")
    case["consent"]["recorded_at"] = "2026-01-01T00:00:00"  # no time zone
    reply = json.loads(handle(build_services(settings).auditpulse, json.dumps(case)))
    assert "error" in reply


@pytest.mark.parametrize(
    "tamper",
    [
        lambda files: files | {"signing-key.pub.pem": b"garbage"},
        lambda files: (
            files
            | {
                "manifest.json": json.dumps(
                    {"files": [], "chain": {"head": "x"}, "case_id": "c"}
                ).encode()
            }
        ),
    ],
)
def test_tampered_packs_are_reported_not_raised(coordinator: Coordinator, tamper) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    pack = coordinator.export_audit_pack(case.case_id, "o")
    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in tamper(files).items():
            archive.writestr(name, data)
    assert not verify_pack(out.getvalue()).valid


def test_zip_bombs_are_refused() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"\0" * (101 * 1024 * 1024))
    assert verify_pack(out.getvalue()).problems == ["pack is larger than any genuine audit pack"]


def test_iap_header_is_ignored_unless_trusted(settings: Settings) -> None:
    header = {"X-Goog-Authenticated-User-Email": "accounts.google.com:chief@lender"}
    client = TestClient(create_app(settings))
    case = client.post("/demo-cases/synthetic-grocer-kandy", headers=header).json()
    assert client.get(f"/cases/{case['case_id']}/audit").json()["events"][0]["actor"] == "officer"
    settings.trust_iap_header = True
    trusted = TestClient(create_app(settings))
    case = trusted.post("/demo-cases/synthetic-grocer-kandy", headers=header).json()
    assert (
        trusted.get(f"/cases/{case['case_id']}/audit").json()["events"][0]["actor"]
        == "chief@lender"
    )


def test_case_list_rejects_bad_limits_and_orders_by_activity(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/cases", params={"limit": -5}).status_code == 422
    first = client.post("/demo-cases/synthetic-grocer-kandy").json()["case_id"]
    second = client.post("/demo-cases/synthetic-warung-jakarta").json()["case_id"]
    client.post(f"/cases/{first}/assess")  # the older case becomes the most recently active
    listed = [c["case_id"] for c in client.get("/cases").json()]
    assert listed[:2] == [first, second]
    assert (DEMO / "synthetic-grocer-kandy").exists()
