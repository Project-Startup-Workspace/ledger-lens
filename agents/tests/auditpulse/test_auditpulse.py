"""Rule packs, the rule engine, screening and full compliance reports."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import jsonschema
import pytest

from ledger_lens.auditpulse.agent import AuditPulse
from ledger_lens.auditpulse.disclosure import key_fact_statement
from ledger_lens.auditpulse.packs import FactCheck, RulePack, RulePackRegistry
from ledger_lens.auditpulse.retrieval import PackSummaryRetriever
from ledger_lens.auditpulse.rules import evaluate, resolve
from ledger_lens.auditpulse.screening import SanctionsScreen, normalise
from ledger_lens.shared.config import REPO_ROOT, Settings
from ledger_lens.shared.schemas import (
    Applicant,
    Consent,
    CreditFile,
    EvidenceDocument,
    EvidenceKind,
    FindingStatus,
    LoanRequest,
    OfficerDecision,
    utc_now,
)

PACKS = REPO_ROOT / "rule-packs"


@pytest.mark.parametrize("path", sorted(PACKS.glob("*/pack.json")), ids=lambda p: p.parent.name)
def test_every_pack_matches_the_json_schema(path) -> None:
    schema = json.loads((PACKS / "schema.json").read_text())
    jsonschema.validate(json.loads(path.read_text()), schema)


def test_registry_loads_jurisdictions_and_common_pack() -> None:
    registry = RulePackRegistry(PACKS)
    assert {p.jurisdiction for p in registry.jurisdictions()} == {"lk", "sg", "in"}
    assert registry.common is not None
    assert registry.get("xx") is None
    assert registry.get("LK") is registry.get("lk")


def test_registry_rejects_pack_in_wrong_folder(tmp_path) -> None:
    (tmp_path / "lk-2027").mkdir()
    (tmp_path / "lk-2027" / "pack.json").write_text((PACKS / "lk" / "pack.json").read_text())
    with pytest.raises(ValueError, match="folder"):
        RulePackRegistry(tmp_path)


@pytest.mark.parametrize(
    "check",
    [
        {"fact": "applicant.age", "op": "gte"},
        {"fact": "storage.region", "op": "in", "value": "asia-south1"},
        {"all": []},
    ],
)
def test_malformed_checks_fail_at_load(check: dict) -> None:
    data = json.loads((PACKS / "lk" / "pack.json").read_text())
    data["rules"][0]["check"] = check
    with pytest.raises(ValueError):
        RulePack.model_validate(data)


def test_rules_need_a_citation() -> None:
    data = json.loads((PACKS / "lk" / "pack.json").read_text())
    data["rules"][0]["cites"] = []
    with pytest.raises(ValueError):
        RulePack.model_validate(data)


def test_pack_rejects_citation_to_unknown_clause() -> None:
    data = json.loads((PACKS / "lk" / "pack.json").read_text())
    data["rules"][0]["cites"] = [{"source": "lk-mcra-2026", "clause": "nope"}]
    with pytest.raises(ValueError, match="unknown"):
        RulePack.model_validate(data)


FACTS: dict[str, Any] = {"a": {"n": 5, "flag": True, "items": [], "name": "x"}}


@pytest.mark.parametrize(
    ("op", "fact", "value", "expected"),
    [
        ("present", "a.name", None, True),
        ("present", "a.missing", None, False),
        ("true", "a.flag", None, True),
        ("empty", "a.items", None, True),
        ("empty", "a.missing", None, False),
        ("empty", "a.n", None, False),  # a number is never "empty"
        ("gte", "a.n", 5, True),
        ("lt", "a.n", 5, False),
        ("gte", "a.flag", 0, False),  # booleans are not numbers
        ("in", "a.name", ["x", "y"], True),
        ("eq", "a.missing", "x", False),
    ],
)
def test_evaluate_ops(op: str, fact: str, value: Any, expected: bool) -> None:
    assert evaluate(FactCheck(fact=fact, op=op, value=value), FACTS) is expected  # type: ignore[arg-type]


def test_resolve_handles_non_dict_paths() -> None:
    assert resolve(FACTS, "a.n.deeper") is None


def test_screening_tolerates_accents_order_and_spelling() -> None:
    screen = SanctionsScreen(PACKS / "common" / "sanctions-sample.json")
    assert normalise("Trần Văn Hùng") == normalise("Hung Tran Van")
    for name in [
        "Trần Văn Hùng",
        "Hung Tran Van",
        "Tran Van Hong",
        "Tran Hung",
        "Hung Tran Van Minh",
    ]:
        assert screen.screen([name]), name
    assert not screen.screen(["Kamala Perera", "", "Hung"])


def test_key_fact_statement_terms() -> None:
    loan = LoanRequest(
        amount=Decimal(100_000), currency="LKR", tenor_months=12, annual_rate_pct=12, purpose="x"
    )
    kfs = key_fact_statement(loan)
    assert (kfs.instalment, kfs.instalments, kfs.total_repayable) == (
        Decimal("8884.88"),
        12,
        Decimal("106618.56"),
    )


def make_case(birth: date = date(1985, 1, 1), guarantor: str | None = None) -> CreditFile:
    loan = LoanRequest(
        amount=Decimal(100_000), currency="LKR", tenor_months=12, annual_rate_pct=24, purpose="x"
    )
    return CreditFile(
        jurisdiction="lk",
        applicant=Applicant(
            full_name="Kamala Perera",
            date_of_birth=birth,
            national_id="1",
            phone="1",
            business_name="B",
            business_type="shop",
            years_in_business=5,
            guarantor_name=guarantor,
        ),
        loan=loan,
        consent=Consent(given=True),
        disclosure=key_fact_statement(loan),
    )


@pytest.fixture
def auditpulse(settings: Settings) -> AuditPulse:
    return AuditPulse(
        RulePackRegistry(PACKS),
        PackSummaryRetriever(),
        SanctionsScreen(PACKS / "common" / "sanctions-sample.json"),
        settings,
    )


def statuses(report) -> dict[str, FindingStatus]:
    return {f.rule_id: f.status for f in report.findings}


def test_sri_lanka_before_decision(auditpulse: AuditPulse) -> None:
    report = auditpulse.check(make_case())
    assert report.rule_pack_version == "common@2026.10.2+lk@2026.10.2"
    assert statuses(report) == {
        "ALL-CON-01": FindingStatus.PASS,
        "ALL-SAN-01": FindingStatus.PASS,
        "LK-LIC-01": FindingStatus.PASS,
        "LK-DOC-01": FindingStatus.PENDING,
        "LK-AGE-01": FindingStatus.PASS,
    }
    assert all(f.citations and f.citations[0].excerpt for f in report.findings)


def test_minor_fails_and_sanctions_match_goes_to_review(auditpulse: AuditPulse) -> None:
    minor = make_case(birth=utc_now().date() - timedelta(days=17 * 365), guarantor="Tran Van Hung")
    result = statuses(auditpulse.check(minor))
    assert result["LK-AGE-01"] is FindingStatus.FAIL
    assert result["ALL-SAN-01"] is FindingStatus.REVIEW


def test_jurisdiction_switch_changes_the_checklist(auditpulse: AuditPulse) -> None:
    case = make_case()
    sg = statuses(auditpulse.check(case, "sg"))
    india = statuses(auditpulse.check(case, "in"))
    assert sg["SG-HUM-01"] is FindingStatus.PENDING
    assert sg["SG-VAL-01"] is FindingStatus.FAIL  # no risk result yet, so no model version
    assert india["IN-APR-01"] is FindingStatus.PASS
    assert india["IN-DAT-01"] is FindingStatus.REVIEW  # local storage is not in India


def decide(case: CreditFile, outcome: str, acknowledged_first: bool = True) -> CreditFile:
    acknowledged = utc_now()
    case.decision = OfficerDecision(
        officer_id="officer-7", outcome=outcome, recommended="approve", reason="Reviewed"
    )
    if not acknowledged_first:
        acknowledged = case.decision.decided_at + timedelta(minutes=5)
    case.disclosure = case.disclosure.model_copy(update={"acknowledged_at": acknowledged})  # type: ignore[union-attr]
    return case


def test_post_decision_rules_resolve_after_approval(auditpulse: AuditPulse) -> None:
    case = decide(make_case(), "approve")
    assert statuses(auditpulse.check(case, "in"))["IN-KFS-01"] is FindingStatus.PASS
    assert statuses(auditpulse.check(case, "lk"))["LK-DOC-01"] is FindingStatus.PASS


def test_agreement_rules_do_not_apply_to_a_decline(auditpulse: AuditPulse) -> None:
    case = decide(make_case(), "decline")
    assert statuses(auditpulse.check(case, "lk"))["LK-DOC-01"] is FindingStatus.NOT_APPLICABLE
    assert statuses(auditpulse.check(case, "sg"))["SG-HUM-01"] is FindingStatus.PASS


def test_kfs_acknowledged_after_the_decision_fails(auditpulse: AuditPulse) -> None:
    case = decide(make_case(), "approve", acknowledged_first=False)
    assert statuses(auditpulse.check(case, "in"))["IN-KFS-01"] is FindingStatus.FAIL


def test_consent_recorded_after_evidence_fails(auditpulse: AuditPulse) -> None:
    case = make_case()
    case.evidence = [
        EvidenceDocument(
            kind=EvidenceKind.NOTEBOOK,
            filename="p.png",
            content_type="image/png",
            sha256="-",
            blob_key="k",
            uploaded_at=case.consent.recorded_at - timedelta(hours=1),
        )
    ]
    assert statuses(auditpulse.check(case))["ALL-CON-01"] is FindingStatus.FAIL


def test_unknown_jurisdiction_still_runs_common_checks(auditpulse: AuditPulse) -> None:
    report = auditpulse.check(make_case(), "ID")
    assert report.jurisdiction == "id"
    assert statuses(report)["ALL-CON-01"] is FindingStatus.PASS
    assert statuses(report)["ALL-PCK-01"] is FindingStatus.REVIEW


def test_model_record_reads_the_active_artifact(settings: Settings, tmp_path) -> None:
    from ledger_lens.shared.governance import bias_report_path, model_record

    active = tmp_path / "current.json"
    active.write_text(settings.risk_model_path.read_text())
    version = json.loads(active.read_text())["version"]
    record = model_record(active, version)
    assert record and record.validation_auc and not record.bias_report
    bias_report_path(active).write_text('{"four_fifths_ratio": 0.97}')
    assert model_record(active, version).bias_report  # type: ignore[union-attr]
    assert model_record(active, "older-version").validation_auc is None  # type: ignore[union-attr]


def test_missing_licence_fails(auditpulse: AuditPulse, settings: Settings) -> None:
    settings.lender_licences = {}
    assert statuses(auditpulse.check(make_case()))["LK-LIC-01"] is FindingStatus.FAIL
