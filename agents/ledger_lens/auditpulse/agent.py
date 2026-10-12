"""AuditPulse: deterministic compliance checks, each finding citing its source.

Pass or fail is decided by code from versioned rule packs, never by a model, so the
same case always produces the same checklist (see docs/adr/0002).
"""

import logging

from ledger_lens.auditpulse.facts import build_facts, model_record
from ledger_lens.auditpulse.packs import Rule, RulePack, RulePackRegistry
from ledger_lens.auditpulse.retrieval import ClauseRetriever
from ledger_lens.auditpulse.rules import evaluate
from ledger_lens.auditpulse.screening import SanctionsScreen
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import (
    Citation,
    ComplianceReport,
    CreditFile,
    Finding,
    FindingStatus,
)

log = logging.getLogger(__name__)


class AuditPulse:
    def __init__(
        self,
        packs: RulePackRegistry,
        retriever: ClauseRetriever,
        sanctions: SanctionsScreen,
        settings: Settings,
    ) -> None:
        self._packs = packs
        self._retriever = retriever
        self._sanctions = sanctions
        self._settings = settings

    def jurisdictions(self) -> list[RulePack]:
        return self._packs.jurisdictions()

    def check(self, case: CreditFile, jurisdiction: str | None = None) -> ComplianceReport:
        """Run the common pack and the jurisdiction's pack against the case.

        `jurisdiction` defaults to the case's own; passing another shows how the same
        case fares under a different regulator (the demo's jurisdiction switcher).
        """
        code = (jurisdiction or case.jurisdiction).lower()
        pack = self._packs.get(code)
        hits = self._sanctions.screen(
            [case.applicant.full_name, case.applicant.guarantor_name or ""]
        )
        record = model_record(
            self._settings.risk_model_path, case.risk.model_version if case.risk else None
        )
        facts = build_facts(case, code, self._settings, hits, record)
        packs = [p for p in (self._packs.common, pack) if p is not None]
        outcome = case.decision.outcome if case.decision else None
        findings = [self._finding(p, rule, facts, outcome) for p in packs for rule in p.rules]
        if pack is None:
            # Still run the common checks, and say plainly that local rules are missing.
            findings.append(_missing_pack_finding(code))
        version = "+".join(f"{p.jurisdiction}@{p.version}" for p in packs)
        log.info("compliance checked", extra={"jurisdiction": code, "packs": version})
        return ComplianceReport(
            jurisdiction=code,
            jurisdiction_name=pack.name if pack else f"No rule pack ({code.upper()})",
            rule_pack_version=version,
            findings=findings,
        )

    def _finding(
        self, pack: RulePack, rule: Rule, facts: dict[str, object], outcome: str | None
    ) -> Finding:
        if rule.stage == "post_decision" and outcome is None:
            status, detail = FindingStatus.PENDING, "Checked once the officer records a decision."
        elif rule.stage == "post_decision" and outcome not in rule.outcomes:
            status, detail = FindingStatus.NOT_APPLICABLE, f"Does not apply to a {outcome}."
        elif evaluate(rule.check, facts):
            status, detail = FindingStatus.PASS, rule.pass_detail
        else:
            status = FindingStatus.FAIL if rule.on_fail == "fail" else FindingStatus.REVIEW
            detail = rule.fail_detail
        return Finding(
            rule_id=rule.id,
            title=rule.title,
            status=status,
            severity=rule.severity,
            detail=detail,
            citations=[self._citation(pack, c.source, c.clause) for c in rule.cites],
        )

    def _citation(self, pack: RulePack, source_id: str, clause_id: str) -> Citation:
        source, clause = pack.clauses[(source_id, clause_id)]
        return Citation(
            source_id=source.id,
            title=source.title,
            clause=clause.reference,
            url=source.url,
            excerpt=self._retriever.excerpt(source, clause),
        )


def _missing_pack_finding(code: str) -> Finding:
    return Finding(
        rule_id="ALL-PCK-01",
        title="Local lending rules are available",
        status=FindingStatus.REVIEW,
        severity="major",
        detail=f"There is no rule pack for '{code}'. Local rules must be checked by hand.",
        citations=[],
    )
