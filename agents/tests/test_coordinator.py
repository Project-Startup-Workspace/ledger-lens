"""End-to-end runs of the coordinator on the synthetic demo cases, fully offline."""

import pytest

from ledger_lens.audit_trail.chain import verify_chain
from ledger_lens.audit_trail.pack import verify_pack
from ledger_lens.coordinator import CaseStateError, Coordinator, build_services
from ledger_lens.demo import demo_cases, open_demo_case
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import (
    CaseStatus,
    Consent,
    EvidenceKind,
    FindingStatus,
    RiskGrade,
)
from ledger_lens.shared.storage import LocalBlobStore, check_key


@pytest.fixture
def coordinator(settings: Settings) -> Coordinator:
    return Coordinator(build_services(settings))


def test_demo_cases_are_listed() -> None:
    assert demo_cases() == [
        "synthetic-grocer-kandy",
        "synthetic-market-stall-hcmc",
        "synthetic-warung-jakarta",
    ]


def test_kandy_case_runs_end_to_end(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    case = coordinator.assess(case.case_id, "officer-1")
    assert case.status is CaseStatus.ASSESSED
    assert case.risk and case.risk.grade is RiskGrade.A and case.risk.recommendation == "approve"
    assert case.consistency and case.consistency.status == "compared"
    assert case.compliance and case.disclosure and case.explanation
    assert verify_chain(coordinator.audit_events(case.case_id)).valid


def test_jakarta_case_is_referred_for_the_planted_week(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-warung-jakarta", "officer-1")
    case = coordinator.assess(case.case_id, "officer-1")
    assert case.risk and case.risk.recommendation == "refer"
    assert case.risk.path_to_approval[0].feature == "consistency_flags"


def test_decision_completes_compliance_and_the_audit_pack_verifies(
    coordinator: Coordinator,
) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id, "officer-1")
    coordinator.acknowledge_disclosure(case.case_id, blank_fields=[], actor="officer-1")
    decided = coordinator.decide(
        case.case_id, officer_id="officer-1", outcome="approve", reason="Steady sales"
    )
    statuses = {f.rule_id: f.status for f in decided.compliance.findings}  # type: ignore[union-attr]
    assert statuses["LK-DOC-01"] is FindingStatus.PASS
    assert FindingStatus.PENDING not in statuses.values()

    pack = coordinator.export_audit_pack(case.case_id, "officer-1")
    result = verify_pack(pack, trusted_public_key=coordinator.signing_public_key())
    assert result.valid and result.key_trusted
    events = [e.event_type for e in coordinator.audit_events(case.case_id)]
    assert events[0] == "case_created" and events[-1] == "audit_pack_exported"
    assert "decision_recorded" in events


def test_state_rules_are_enforced(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    with pytest.raises(CaseStateError, match="assess"):
        coordinator.decide(case.case_id, officer_id="o", outcome="approve", reason="x")
    coordinator.assess(case.case_id)
    with pytest.raises(CaseStateError, match="reason"):
        coordinator.decide(case.case_id, officer_id="o", outcome="approve", reason="  ")
    coordinator.decide(case.case_id, officer_id="o", outcome="decline", reason="Policy")
    with pytest.raises(CaseStateError, match="decided"):
        coordinator.add_evidence(
            case.case_id,
            kind=EvidenceKind.NOTEBOOK,
            filename="p.png",
            content_type="image/png",
            data=b"x",
            actor="o",
        )


def test_evidence_needs_consent(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    created = coordinator.create_case(
        applicant=case.applicant,
        loan=case.loan,
        consent=Consent(given=False),
        jurisdiction="lk",
        actor="o",
    )
    with pytest.raises(CaseStateError, match="consent"):
        coordinator.add_evidence(
            created.case_id,
            kind=EvidenceKind.NOTEBOOK,
            filename="p.png",
            content_type="image/png",
            data=b"x",
            actor="o",
        )


def test_compliance_view_does_not_change_the_case(coordinator: Coordinator) -> None:
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id)
    view = coordinator.compliance_view(case.case_id, "sg")
    assert view.jurisdiction == "sg"
    assert coordinator.get(case.case_id).compliance.jurisdiction == "lk"  # type: ignore[union-attr]


@pytest.mark.parametrize("key", ["../escape", "/etc/passwd", "a/../../b", ""])
def test_storage_keys_cannot_escape_the_root(key: str, tmp_path) -> None:
    with pytest.raises(ValueError):
        check_key(key)
    with pytest.raises(ValueError):
        LocalBlobStore(tmp_path).put(key, b"x", "text/plain")
