"""Coordinator: runs the five agents on a case, in order, and records every step.

Each stage is a public method, so the HTTP API, the ADK workflow and tests all drive
exactly the same logic. Every state change is saved and appended to the audit chain.
"""

import contextvars
import hashlib
import logging
import threading
import weakref
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol
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
from ledger_lens.explain.agent import TEMPLATE, ExplainAgent, officer_report
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
    AuditFinding,
    CaseStatus,
    ComplianceReport,
    Consent,
    CreditFile,
    CreditReview,
    Disclosure,
    Engagement,
    EvidenceDocument,
    EvidenceKind,
    EvidenceRequest,
    Explanation,
    ExtractionResult,
    LoanRequest,
    OfficerDecision,
    utc_now,
)
from ledger_lens.shared.storage import (
    BlobStore,
    CaseRepository,
    OrgField,
    build_blob_store,
    build_case_repository,
)
from ledger_lens.shared.usage import CallBudget, Limit, MeteredLlm, metered

SYSTEM = "system"
log = logging.getLogger(__name__)
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
    budget: CallBudget | None = None  # None when model calls are not counted


def build_services(settings: Settings, daily_limit: Limit | None = None) -> Services:
    """`daily_limit` replaces the deployment's daily model-call cap, e.g. with a live one."""
    llm = metered(build_llm(settings), settings, daily_limit)
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
        budget=llm.budget if isinstance(llm, MeteredLlm) else None,
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
        lender_org_id: str | None = None,
        business_org_id: str | None = None,
    ) -> CreditFile:
        case = CreditFile(
            jurisdiction=jurisdiction.lower(),
            applicant=applicant,
            loan=loan,
            consent=consent,
            lender_org_id=lender_org_id,
            business_org_id=business_org_id,
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
                    "lender": lender_org_id,
                    "business": business_org_id,
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

    def list_cases_for(
        self, field: OrgField, org_ids: set[str], limit: int = 50
    ) -> list[CreditFile]:
        return self._s.cases.list_for(field, org_ids, limit) if org_ids else []

    def send_application(self, case_id: str, lender_org_id: str, actor: str) -> CreditFile:
        """The owner sends their application to a lender, which from then on works it."""
        with self._case(case_id) as case:
            if case.business_org_id is None or case.lender_org_id is not None:
                raise CaseStateError("the application has already been sent")
            case.lender_org_id = lender_org_id
            self._save(case, "application_sent", actor, {"lender": lender_org_id})
            return case

    # --- Reviews, requests and engagements -------------------------------------------

    def assign_credit_review(
        self, case_id: str, *, reviewer_uid: str, reviewer: str, actor: str
    ) -> CreditFile:
        """A loan officer sends the case to a credit reviewer, who then decides it."""
        with self._case(case_id) as case:
            self._require_assessed(case)
            self._require_open(case)
            case.credit_review = CreditReview(
                reviewer_uid=reviewer_uid, reviewer=reviewer, requested_by=actor
            )
            self._save(case, "credit_review_assigned", actor, {"reviewer": reviewer})
            return case

    def add_request(
        self,
        case_id: str,
        *,
        from_org_id: str,
        addressed_to: Literal["lender", "business"],
        message: str,
        actor: str,
    ) -> CreditFile:
        """Ask the lender or the business for evidence or an explanation."""
        with self._case(case_id) as case:
            if addressed_to == "business" and case.business_org_id is None:
                raise CaseStateError("this case has no business account to ask")
            if addressed_to == "lender" and case.lender_org_id is None:
                raise CaseStateError("this application has not been sent to a lender")
            request = EvidenceRequest(
                from_org_id=from_org_id,
                requested_by=actor,
                addressed_to=addressed_to,
                message=_required(message, "a message"),
            )
            case.requests.append(request)
            self._save(
                case,
                "evidence_requested",
                actor,
                {"request": request.id, "to": addressed_to, "from": from_org_id},
            )
            return case

    def answer_request(
        self, case_id: str, request_id: str, *, answer: str, actor: str
    ) -> CreditFile:
        with self._case(case_id) as case:
            request = _find(case.requests, request_id)
            if request.answer is not None:
                raise CaseStateError("the request is already answered")
            request.answer = _required(answer, "an answer")
            request.answered_by, request.answered_at = actor, utc_now()
            self._save(
                case,
                "evidence_request_answered",
                actor,
                {"request": request.id, "answer_sha256": sha256_hex(request.answer.encode())},
            )
            return case

    def assign_engagement(
        self,
        case_id: str,
        *,
        audit_firm_id: str,
        assignee_uid: str,
        assignee: str,
        actor: str,
    ) -> CreditFile:
        """An audit firm's admin assigns the case to one of its audit officers."""
        with self._case(case_id) as case:
            if any(
                e.audit_firm_id == audit_firm_id and e.status != "approved"
                for e in case.engagements
            ):
                raise CaseStateError("your firm already has an engagement open on this case")
            engagement = Engagement(
                audit_firm_id=audit_firm_id,
                assignee_uid=assignee_uid,
                assignee=assignee,
                assigned_by=actor,
            )
            case.engagements.append(engagement)
            self._save(
                case,
                "engagement_assigned",
                actor,
                {"engagement": engagement.id, "audit_firm": audit_firm_id, "assignee": assignee},
            )
            return case

    def add_finding(
        self,
        case_id: str,
        engagement_id: str,
        *,
        severity: Literal["observation", "issue"],
        note: str,
        actor: str,
    ) -> CreditFile:
        """A finding, pinned to the case as it was when written."""
        with self._case(case_id) as case:
            engagement = _find(case.engagements, engagement_id)
            if engagement.status not in ("open", "returned"):
                raise CaseStateError("the engagement is with the reviewer")
            finding = AuditFinding(
                author=actor,
                severity=severity,
                note=_required(note, "a note"),
                snapshot=snapshot_hash(case),
            )
            engagement.findings.append(finding)
            self._save(
                case,
                "audit_finding_recorded",
                actor,
                {
                    "engagement": engagement.id,
                    "severity": severity,
                    "snapshot": finding.snapshot,
                    "note_sha256": sha256_hex(finding.note.encode()),
                },
            )
            return case

    def submit_engagement(self, case_id: str, engagement_id: str, *, actor: str) -> CreditFile:
        with self._case(case_id) as case:
            engagement = _find(case.engagements, engagement_id)
            if engagement.status not in ("open", "returned"):
                raise CaseStateError("the engagement is not open")
            if not engagement.findings:
                raise CaseStateError("record at least one finding first")
            engagement.status = "submitted"
            self._save(case, "engagement_submitted", actor, {"engagement": engagement.id})
            return case

    def review_engagement(
        self, case_id: str, engagement_id: str, *, approve: bool, note: str, actor: str
    ) -> CreditFile:
        """The audit reviewer approves the findings as the final report, or returns them."""
        with self._case(case_id) as case:
            engagement = _find(case.engagements, engagement_id)
            if engagement.status != "submitted":
                raise CaseStateError("the engagement has not been submitted for review")
            if actor == engagement.assignee:
                raise CaseStateError("findings are approved by someone other than their author")
            engagement.status = "approved" if approve else "returned"
            engagement.reviewed_by, engagement.reviewed_at = actor, utc_now()
            engagement.review_note = note.strip() or None
            if approve:
                engagement.report_snapshot = snapshot_hash(case)
            self._save(
                case,
                "audit_report_approved" if approve else "engagement_returned",
                actor,
                {"engagement": engagement.id, "snapshot": engagement.report_snapshot},
            )
            return case

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
            # Wake on the first failure, whichever page it is, and cancel what has not started.
            wait(futures, return_when=FIRST_EXCEPTION)
            if any(f.done() and f.exception() is not None for f in futures):
                for future in futures:
                    future.cancel()
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
        """Agent 5. Translations of older facts are dropped; the template is never kept,
        so the next request can try the model again."""
        explanation = self._s.explain.explain(case, language)
        language = explanation.borrower_language
        reused = case.translations.get(language) == explanation
        case.explanation = explanation
        if explanation.written_by != TEMPLATE:
            case.translations = {
                code: kept
                for code, kept in case.translations.items()
                if kept.facts_digest == explanation.facts_digest
            } | {language: explanation}
        self._save(
            case,
            "explanation_written",
            actor,
            {"language": language, "written_by": explanation.written_by, "reused": reused},
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
        text, language = case.explanation.borrower_text, case.explanation.borrower_language
        # Audio is saved beside the evidence, so playing it again costs no model call. The
        # key covers everything that changes the sound, so a new explanation is spoken anew.
        settings = self._s.settings
        voice = "\n".join([settings.model_tts, settings.tts_voice, language, text])
        key = f"speech/{case_id}/{hashlib.sha256(voice.encode()).hexdigest()[:32]}.wav"
        # One request per audio file speaks at a time, so a double press pays once. The key
        # is not a case id, so the case itself stays unlocked while speech is generated.
        with self._lock_for(key):
            if (audio := self._s.blobs.find(key)) is not None:
                return audio
            audio = self._s.explain.speak(text, language)
            try:
                self._s.blobs.put(key, audio, "audio/wav")
            except Exception:
                # The audio is paid for; serve it and let the next play try saving again.
                log.warning("could not save spoken explanation", exc_info=True)
            return audio

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


class _HasId(Protocol):
    id: str


def _find[T: _HasId](items: list[T], item_id: str) -> T:
    found = next((i for i in items if i.id == item_id), None)
    if found is None:
        raise CaseNotFoundError(item_id)
    return found


def _required(text: str, what: str) -> str:
    if not text.strip():
        raise CaseStateError(f"{what} is required")
    return text.strip()


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
