"""Coordinator: runs the five agents on a case, in order, and records every step.

Each stage is a public method, so the HTTP API, the ADK workflow and tests all drive
exactly the same logic. Every state change is saved and appended to the audit chain.
"""

import contextvars
import threading
import weakref
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from ledger_lens.audit_trail.chain import (
    AuditEvent,
    AuditStore,
    ChainVerification,
    sha256_hex,
    verify_chain,
)
from ledger_lens.audit_trail.pack import build_pack, snapshot_hash
from ledger_lens.audit_trail.signing import Signer, build_signer
from ledger_lens.audit_trail.stores import build_audit_store
from ledger_lens.auditpulse.agent import AuditPulse
from ledger_lens.auditpulse.disclosure import key_fact_statement
from ledger_lens.auditpulse.packs import RulePackRegistry
from ledger_lens.auditpulse.retrieval import build_retriever
from ledger_lens.auditpulse.screening import SanctionsScreen
from ledger_lens.consistency.agent import ConsistencyAgent
from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.evidence.tools import weekly_cash_flow
from ledger_lens.explain.agent import ExplainAgent, officer_report
from ledger_lens.risk.agent import RiskAgent
from ledger_lens.risk.model import LogisticModel
from ledger_lens.risk.model_card import model_card
from ledger_lens.shared.config import Settings
from ledger_lens.shared.governance import artifact_fingerprint, artifact_for_version
from ledger_lens.shared.llm import build_llm
from ledger_lens.shared.logs import case_context
from ledger_lens.shared.pii import pseudonym
from ledger_lens.shared.safety import build_safety_screen
from ledger_lens.shared.schemas import (
    Applicant,
    CaseStatus,
    ComplianceReport,
    Consent,
    CreditFile,
    Disclosure,
    EvidenceDocument,
    EvidenceKind,
    Explanation,
    ExtractionResult,
    LoanRequest,
    OfficerDecision,
    utc_now,
)
from ledger_lens.shared.storage import (
    BlobStore,
    CaseRepository,
    build_blob_store,
    build_case_repository,
)

SYSTEM = "system"
READ_WORKERS = 4  # concurrent model calls per assessment


class CaseNotFoundError(LookupError):
    pass


class CaseStateError(ValueError):
    """The request does not fit the case's current state, e.g. deciding before assessing."""


@dataclass
class Services:
    """Everything the coordinator needs, built once per process."""

    settings: Settings
    evidence: EvidenceAgent
    consistency: ConsistencyAgent
    risk: RiskAgent
    model: LogisticModel
    auditpulse: AuditPulse
    explain: ExplainAgent
    cases: CaseRepository
    blobs: BlobStore
    packs: BlobStore
    audit: AuditStore
    signer: Signer


def build_services(settings: Settings) -> Services:
    llm = build_llm(settings)
    safety = build_safety_screen(settings)
    model = LogisticModel.load(settings.risk_model_path)
    fingerprint = artifact_fingerprint(settings.risk_model_path)
    return Services(
        settings=settings,
        evidence=EvidenceAgent(llm, safety, settings),
        consistency=ConsistencyAgent(settings),
        risk=RiskAgent(model, fingerprint),
        model=model,
        auditpulse=AuditPulse(
            RulePackRegistry(settings.rule_packs_dir),
            build_retriever(settings),
            SanctionsScreen(settings.sanctions_list_path),
            settings,
        ),
        explain=ExplainAgent(llm, safety, settings),
        cases=build_case_repository(settings),
        blobs=build_blob_store(settings, settings.evidence_bucket, "evidence"),
        packs=build_blob_store(settings, settings.audit_bucket, "audit-packs"),
        audit=build_audit_store(settings),
        signer=build_signer(settings),
    )


class Coordinator:
    def __init__(self, services: Services) -> None:
        self._s = services
        # Locks live only while someone holds them, so the map cannot grow without bound.
        # They serialise requests within this process; revisions guard across instances.
        self._locks: weakref.WeakValueDictionary[str, threading.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._locks_guard = threading.Lock()

    # --- Case lifecycle ---------------------------------------------------------------

    def create_case(
        self,
        *,
        applicant: Applicant,
        loan: LoanRequest,
        consent: Consent,
        jurisdiction: str,
        actor: str,
    ) -> CreditFile:
        case = CreditFile(
            jurisdiction=jurisdiction.lower(), applicant=applicant, loan=loan, consent=consent
        )
        with self._context(case):
            self._s.cases.save(case)
            self._record(
                case,
                "case_created",
                actor,
                {
                    "applicant": pseudonym(applicant.national_id),
                    "jurisdiction": case.jurisdiction,
                    "amount": str(loan.amount),
                    "currency": loan.currency,
                },
            )
            self._record(
                case,
                "consent_recorded",
                actor,
                {"given": consent.given, "method": consent.method, "text": consent.text_version},
            )
        return case

    def get(self, case_id: str) -> CreditFile:
        case = self._s.cases.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return case

    def list_cases(self, limit: int = 50) -> list[CreditFile]:
        return self._s.cases.list(limit)

    def add_evidence(
        self,
        case_id: str,
        *,
        kind: EvidenceKind,
        filename: str,
        content_type: str,
        data: bytes,
        actor: str,
    ) -> EvidenceDocument:
        with self._case(case_id) as case:
            if not case.consent.given:
                raise CaseStateError("consent must be recorded before evidence is uploaded")
            if case.status is CaseStatus.DECIDED:
                raise CaseStateError("the case is decided; open a new case for new evidence")
            digest = sha256_hex(data)
            if any(d.sha256 == digest for d in case.evidence):
                # The same page twice would count its sales twice.
                raise CaseStateError(f"'{filename}' was already uploaded to this case")
            doc = EvidenceDocument(
                kind=kind,
                filename=filename,
                content_type=content_type,
                sha256=digest,
                blob_key="",
            )
            doc.blob_key = f"{case.case_id}/{doc.id}"
            self._s.blobs.put(doc.blob_key, data, content_type)
            case.evidence.append(doc)
            case.status = CaseStatus.DRAFT  # new evidence means the assessment is stale
            self._save(
                case,
                "evidence_uploaded",
                actor,
                {"evidence_id": doc.id, "kind": kind, "sha256": digest},
            )
            return doc

    def evidence_file(self, case_id: str, evidence_id: str) -> tuple[bytes, str]:
        case = self.get(case_id)
        doc = next((d for d in case.evidence if d.id == evidence_id), None)
        if doc is None:
            raise CaseNotFoundError(f"{case_id}/{evidence_id}")
        return self._s.blobs.get(doc.blob_key), doc.content_type

    # --- Assessment stages ------------------------------------------------------------

    def assess(self, case_id: str, actor: str = SYSTEM) -> CreditFile:
        """Run every stage in order. Each stage is also callable on its own."""
        with self._case(case_id) as case:
            self._require_open(case)
            for stage in (
                self.read_evidence,
                self.check_consistency,
                self.score_risk,
                self.check_compliance,
                self.write_explanation,
            ):
                stage(case, actor)
            self.mark_assessed(case, actor)
            return case

    def run_stage(self, case_id: str, stage: Callable[[CreditFile], None]) -> CreditFile:
        """Run one stage under the case lock (used by the ADK workflow)."""
        with self._case(case_id) as case:
            self._require_open(case)
            stage(case)
            return case

    def finish_assessment(self, case: CreditFile, actor: str = SYSTEM) -> None:
        """Last stage: the borrower explanation, then the case is marked assessed."""
        self.write_explanation(case, actor)
        self.mark_assessed(case, actor)

    def mark_assessed(self, case: CreditFile, actor: str = SYSTEM) -> None:
        case.status = CaseStatus.ASSESSED
        self._save(case, "case_assessed", actor, {"snapshot": snapshot_hash(case)})

    def read_evidence(self, case: CreditFile, actor: str = SYSTEM) -> None:
        """Agent 1: read any unread evidence, then recompute cash flow."""
        if not any(d.kind is EvidenceKind.NOTEBOOK for d in case.evidence):
            raise CaseStateError("upload at least one notebook page before assessing")
        done = {x.evidence_id for x in case.extractions}
        pending = [d for d in case.evidence if d.id not in done]
        # One reference date for every page read in this assessment: the latest upload, as
        # a local calendar date in the lender's market, so entries written "today" are
        # accepted. Pages read in an earlier assessment keep the date they were read with.
        reference = local_date(max(d.uploaded_at for d in case.evidence), case.jurisdiction)

        def read(doc: EvidenceDocument) -> ExtractionResult:
            return self._s.evidence.read(
                doc,
                self._s.blobs.get(doc.blob_key),
                reference_date=reference,
                currency=case.loan.currency,
            )

        # Pages are independent, so model calls run in parallel, each in a copy of this
        # context so its log lines keep the case id and name masking. On the first failure
        # pages not yet started are cancelled; every page that did succeed is saved, in
        # upload order, so a retry pays only for the pages that failed.
        with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
            futures = [pool.submit(contextvars.copy_context().run, read, d) for d in pending]
            for future in futures:
                if future.exception() is not None:
                    for later in futures:
                        later.cancel()
                    break
        first_error: BaseException | None = None
        for doc, future in zip(pending, futures, strict=True):
            if future.cancelled():
                continue
            if (error := future.exception()) is not None:
                first_error = first_error or error
                continue
            self._record_read(case, doc, future.result(), actor)
        if first_error is not None:
            raise first_error
        notebook = [
            e for x in case.extractions if x.kind is EvidenceKind.NOTEBOOK for e in x.entries
        ]
        case.cash_flow = weekly_cash_flow(
            notebook, case.loan.currency, self._s.settings.min_extraction_confidence
        )
        self._save(
            case,
            "cash_flow_calculated",
            actor,
            {
                "weeks": case.cash_flow.weeks_covered,
                "avg_weekly_net": str(case.cash_flow.avg_weekly_net),
                "for_review": len(case.cash_flow.entries_for_review),
            },
        )

    def _record_read(
        self, case: CreditFile, doc: EvidenceDocument, result: ExtractionResult, actor: str
    ) -> None:
        case.extractions.append(result)
        self._save(
            case,
            "evidence_read",
            actor,
            {
                "evidence_id": doc.id,
                "entries": len(result.entries),
                "model": result.model,
                "warnings": len(result.warnings),
            },
        )

    def check_consistency(self, case: CreditFile, actor: str = SYSTEM) -> None:
        """Agent 2."""
        case.consistency = self._s.consistency.check(case.extractions, case.loan.currency)
        self._save(
            case,
            "consistency_checked",
            actor,
            {"status": case.consistency.status, "flags": len(case.consistency.flags)},
        )

    def score_risk(self, case: CreditFile, actor: str = SYSTEM) -> None:
        """Agent 3, plus the Key Fact Statement that the offer would carry."""
        case.risk = self._s.risk.assess(case)
        offer = key_fact_statement(case.loan)
        # Keep the borrower's acknowledgement when the terms they saw are unchanged.
        if case.disclosure is None or _terms(case.disclosure) != _terms(offer):
            case.disclosure = offer
        self._save(
            case,
            "risk_assessed",
            actor,
            {
                "model": case.risk.model_version,
                "grade": case.risk.grade,
                "probability_of_default": case.risk.probability_of_default,
                "recommendation": case.risk.recommendation,
            },
        )

    def check_compliance(self, case: CreditFile, actor: str = SYSTEM) -> None:
        """Agent 4, under the case's own jurisdiction."""
        case.compliance = self._s.auditpulse.check(case)
        self._save(
            case,
            "compliance_checked",
            actor,
            {
                "jurisdiction": case.compliance.jurisdiction,
                "rule_packs": case.compliance.rule_pack_version,
                "statuses": {f.rule_id: f.status for f in case.compliance.findings},
            },
        )

    def write_explanation(
        self, case: CreditFile, actor: str = SYSTEM, language: str | None = None
    ) -> None:
        """Agent 5."""
        case.explanation = self._s.explain.explain(case, language)
        self._save(
            case,
            "explanation_written",
            actor,
            {
                "language": case.explanation.borrower_language,
                "written_by": case.explanation.written_by,
            },
        )

    # --- Officer actions --------------------------------------------------------------

    def compliance_view(self, case_id: str, jurisdiction: str) -> ComplianceReport:
        """The case under another jurisdiction's rules, without changing the case."""
        return self._s.auditpulse.check(self.get(case_id), jurisdiction)

    def jurisdictions(self) -> list[dict[str, str]]:
        return [
            {"code": p.jurisdiction, "name": p.name, "version": p.version}
            for p in self._s.auditpulse.jurisdictions()
        ]

    def explain_in(self, case_id: str, language: str, actor: str) -> Explanation:
        with self._case(case_id) as case:
            self._require_assessed(case)
            self.write_explanation(case, actor, language)
            assert case.explanation is not None
            return case.explanation

    def officer_report(self, case_id: str) -> str:
        return officer_report(self.get(case_id))

    def speech(self, case_id: str) -> bytes:
        case = self.get(case_id)
        if case.explanation is None:
            raise CaseStateError("write an explanation first")
        return self._s.explain.speak(
            case.explanation.borrower_text, case.explanation.borrower_language
        )

    def acknowledge_disclosure(
        self, case_id: str, *, blank_fields: list[str], actor: str
    ) -> CreditFile:
        """The borrower has seen the Key Fact Statement and the agreement to be signed."""
        with self._case(case_id) as case:
            self._require_assessed(case)
            self._require_open(case)
            assert case.disclosure is not None
            case.disclosure = case.disclosure.model_copy(
                update={"acknowledged_at": utc_now(), "blank_fields": blank_fields}
            )
            self._save(case, "disclosure_acknowledged", actor, {"blank_fields": blank_fields})
            return case

    def decide(
        self,
        case_id: str,
        *,
        officer_id: str,
        outcome: Literal["approve", "decline", "refer"],
        reason: str,
    ) -> CreditFile:
        """Record the officer's decision; the system only ever recommends."""
        with self._case(case_id) as case:
            self._require_assessed(case)
            self._require_open(case)
            assert case.risk is not None
            reason = reason.strip()
            if not reason:
                raise CaseStateError("a reason is required for every decision")
            case.decision = OfficerDecision(
                officer_id=officer_id,
                outcome=outcome,
                recommended=case.risk.recommendation,
                reason=reason,
            )
            case.status = CaseStatus.DECIDED
            self._save(
                case,
                "decision_recorded",
                officer_id,
                {
                    "outcome": outcome,
                    "recommended": case.risk.recommendation,
                    "overridden": case.decision.overridden,
                    "reason_sha256": sha256_hex(reason.encode()),
                },
            )
            self.check_compliance(case, officer_id)
            return case

    # --- Audit ------------------------------------------------------------------------

    def audit_events(self, case_id: str) -> list[AuditEvent]:
        self.get(case_id)
        return self._s.audit.events(case_id)

    def audit_log(self, case_id: str) -> tuple[list[AuditEvent], ChainVerification]:
        """The events and their verification, from a single read."""
        events = self.audit_events(case_id)
        return events, verify_chain(events)

    def export_audit_pack(self, case_id: str, actor: str) -> bytes:
        """Record the export, then sign and store a pack that includes that record.

        Everything that can fail on bad inputs (model card, officer report) is prepared
        before the export event is sealed, so the chain never records an export that
        did not happen.
        """
        with self._case(case_id) as case:
            card = self._model_card_for(case)
            report = officer_report(case)
            compliance = [case.compliance] if case.compliance else []
            exported_at = utc_now()
            seq = len(self._s.audit.events(case.case_id))
            # The event's sequence number makes every stored pack's key unique.
            key = f"{case.case_id}/{exported_at:%Y%m%dT%H%M%SZ}-{seq:05d}.zip"
            self._record(
                case, "audit_pack_exported", actor, {"snapshot": snapshot_hash(case), "key": key}
            )
            try:
                pack = build_pack(
                    case,
                    self._s.audit.events(case.case_id),
                    compliance,
                    card,
                    report,
                    self._s.signer,
                )
                self._s.packs.put(key, pack, "application/zip")
            except Exception:
                self._record(case, "audit_pack_export_failed", SYSTEM, {"key": key})
                raise
            return pack

    def signing_public_key(self) -> bytes:
        return self._s.signer.public_key_pem()

    def _model_card_for(self, case: CreditFile) -> dict[str, Any] | None:
        """Card for the exact artifact that scored this case, which may not be active.

        A missing or unreadable artifact gives a card that says so, rather than failing
        the export: the pack still records everything else about the case.
        """
        if case.risk is None:
            return None
        version, fingerprint = case.risk.model_version, case.risk.model_fingerprint
        path = artifact_for_version(self._s.settings.risk_model_path, version, fingerprint)
        if path is None:
            return {"version": version, "status": "the artifact that scored this case is gone"}
        try:
            model = (
                self._s.model
                if path == self._s.settings.risk_model_path
                else LogisticModel.load(path)
            )
            return model_card(model, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"version": version, "status": f"model card unavailable: {exc}"[:500]}

    # --- Internals --------------------------------------------------------------------

    @contextmanager
    def _case(self, case_id: str) -> Iterator[CreditFile]:
        """Load a case under its lock, so concurrent requests cannot interleave."""
        with self._lock_for(case_id):
            case = self.get(case_id)
            with self._context(case):
                yield case

    def _lock_for(self, case_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(case_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[case_id] = lock
            return lock

    @staticmethod
    @contextmanager
    def _context(case: CreditFile) -> Iterator[None]:
        names = tuple(n for n in (case.applicant.full_name, case.applicant.guarantor_name) if n)
        with case_context(case.case_id, names):
            yield

    def _save(self, case: CreditFile, event: str, actor: str, payload: dict[str, Any]) -> None:
        self._s.cases.save(case)
        self._record(case, event, actor, payload)

    def _record(self, case: CreditFile, event: str, actor: str, payload: dict[str, Any]) -> None:
        self._s.audit.append(case.case_id, event, actor, payload)

    @staticmethod
    def _require_open(case: CreditFile) -> None:
        if case.status is CaseStatus.DECIDED:
            raise CaseStateError("the case is decided and closed")

    @staticmethod
    def _require_assessed(case: CreditFile) -> None:
        if case.status is CaseStatus.DRAFT or case.risk is None:
            raise CaseStateError("assess the case first")


def _terms(disclosure: Disclosure) -> tuple[object, ...]:
    return (
        disclosure.apr_pct,
        disclosure.instalment,
        disclosure.instalments,
        disclosure.total_repayable,
    )


# Local calendar for each market with a rule pack; others fall back to UTC.
MARKET_TIME_ZONES = {"lk": "Asia/Colombo", "sg": "Asia/Singapore", "in": "Asia/Kolkata"}


def local_date(moment: datetime, jurisdiction: str) -> date:
    """The calendar date at `moment` in the market's time zone."""
    return moment.astimezone(ZoneInfo(MARKET_TIME_ZONES.get(jurisdiction, "UTC"))).date()
