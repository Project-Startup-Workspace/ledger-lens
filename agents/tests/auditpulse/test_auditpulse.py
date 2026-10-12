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
    with pytest.raises(KeyError):
        registry.get("xx")


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
        ("gte", "a.n", 5, True),
        ("lt", "a.n", 5, False),
        ("gte", "a.flag", 0, False),  # booleans are not numbers
        ("in", "a.name", ["x", "y"], True),
        ("eq", "a.missing", None, False),
    ],
)
def test_evaluate_ops(op: str, fact: str, value: Any, expected: bool) -> None:
    assert evaluate(FactCheck(fact=fact, op=op, value=value), FACTS) is expected  # type: ignore[arg-type]


def test_resolve_handles_non_dict_paths() -> None:
    assert resolve(FACTS, "a.n.deeper") is None


def test_screening_tolerates_accents_order_and_spelling() -> None:
    screen = SanctionsScreen(PACKS / "common" / "sanctions-sample.json")
    assert normalise("Trần Văn Hùng") == normalise("Hung Tran Van")
    assert screen.screen(["Trần Văn Hùng", "Hung Tran Van", "Tran Van Hong"])
    assert not screen.screen(["Kamala Perera", ""])


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
    assert report.rule_pack_version == "common@2026.10.1+lk@2026.10.1"
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


def test_post_decision_rules_resolve_after_sign_off(auditpulse: AuditPulse) -> None:
    case = make_case()
    case.decision = OfficerDecision(
        officer_id="officer-7", outcome="approve", recommended="approve", reason="Strong file"
    )
    case.disclosure = case.disclosure.model_copy(update={"acknowledged_at": utc_now()})  # type: ignore[union-attr]
    assert statuses(auditpulse.check(case, "in"))["IN-KFS-01"] is FindingStatus.PASS
    assert statuses(auditpulse.check(case, "lk"))["LK-DOC-01"] is FindingStatus.PASS


def test_missing_licence_fails(auditpulse: AuditPulse, settings: Settings) -> None:
    settings.lender_licences = {}
    assert statuses(auditpulse.check(make_case()))["LK-LIC-01"] is FindingStatus.FAIL
