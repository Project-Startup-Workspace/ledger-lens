"""Pydantic contracts passed between agents, stored in case files and served by the API.

Agents never import each other's internals; they exchange only these models.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    model_validator,
)

# Money is exact in memory and a plain number in JSON, so charts need no parsing.
# Timestamps must carry a zone: naive values from external callers cannot be compared
# with the system's UTC times, and ordering checks (consent before evidence) need both.
Timestamp = AwareDatetime
# ISO 4217 codes, normalised to upper case once here so no consumer has to.
CurrencyCode = Annotated[
    str, AfterValidator(str.upper), Field(pattern=r"^[A-Za-z]{3}$", examples=["LKR", "IDR"])
]
# Case ids are also storage keys and file names: they start with a letter or digit, so
# every store (case files, blobs, audit events) accepts exactly the same set.
CASE_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
# Versions safe to use as file names. Enforced where a version is turned into a path,
# not on the contract: external credit files may carry any version string.
MODEL_VERSION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"

Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
JurisdictionCode = Annotated[str, Field(pattern=r"^[a-z]{2}$", examples=["lk", "sg", "in"])]


def new_id(prefix: str) -> str:
    """Return a short random id such as `case_3f9a1c2b7d4e`."""
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base for every contract: reject unknown fields so drift fails loudly."""

    model_config = ConfigDict(extra="forbid")


# --- Evidence ---------------------------------------------------------------------------------


class EvidenceKind(StrEnum):
    NOTEBOOK = "notebook"
    WALLET_STATEMENT = "wallet_statement"
    BANK_STATEMENT = "bank_statement"
    RECEIPT = "receipt"


class Direction(StrEnum):
    IN = "in"  # sales, wallet inflows
    OUT = "out"  # expenses, wallet outflows


class BoundingBox(Contract):
    """Where on a page a value was read, as fractions (0-1) of page width and height."""

    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)


class EvidenceDocument(Contract):
    """One uploaded file. The bytes live in blob storage under `blob_key`."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    kind: EvidenceKind
    filename: str
    content_type: str
    sha256: str
    blob_key: str
    uploaded_at: Timestamp = Field(default_factory=utc_now)


class LedgerEntry(Contract):
    """A single line read from a notebook or statement."""

    id: str = Field(default_factory=lambda: new_id("le"))
    evidence_id: str
    entry_date: date
    description: str
    amount: Money = Field(ge=0)
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    box: BoundingBox | None = None
    raw_text: str = ""


class ExtractionResult(Contract):
    """Everything one evidence agent run read from one document."""

    evidence_id: str
    kind: EvidenceKind
    script: str  # writing system, e.g. "Latin", "Sinhala", "Tamil"
    language: str  # BCP-47 code, e.g. "id", "si"
    currency: str
    entries: list[LedgerEntry]
    warnings: list[str] = []
    model: str


class WeekTotal(Contract):
    """Sales and expenses for one ISO week, Monday to Sunday."""

    week_start: date
    iso_week: str
    sales: Money
    expenses: Money
    net: Money
    entry_count: int


class CashFlowSummary(Contract):
    """Deterministic totals calculated from ledger entries; never produced by a model."""

    currency: CurrencyCode
    weeks: list[WeekTotal]
    total_sales: Money
    total_expenses: Money
    avg_weekly_sales: Money
    avg_weekly_net: Money
    sales_volatility: float  # coefficient of variation of weekly sales
    weeks_covered: int
    entries_for_review: list[LedgerEntry] = []  # excluded because confidence was too low


# --- Consistency -------------------------------------------------------------------------------


class ConsistencyFlag(Contract):
    """A week where the notebook and the wallet disagree more than expected."""

    week_start: date
    notebook_sales: Money
    wallet_inflow: Money
    ratio: float | None  # wallet inflow / notebook sales; None when notebook sales are zero
    expected_ratio: float
    severity: Literal["low", "medium", "high"]
    explanation: str
    officer_question: str


class ConsistencyReport(Contract):
    # insufficient_data: no usable statement, or too few comparable weeks for a baseline
    status: Literal["compared", "insufficient_data"]
    statement_evidence_id: str | None  # the one statement compared, to avoid double counting
    weeks_compared: int
    baseline_ratio: float | None
    flags: list[ConsistencyFlag]
    mismatch_share: float = Field(ge=0, le=1)
    consistency_score: float | None = Field(ge=0, le=1)  # 1 = fully consistent; None = unchecked
    notes: list[str] = []


# --- Risk --------------------------------------------------------------------------------------


class RiskGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ReasonCode(Contract):
    """One feature's contribution to the score, from Shapley values."""

    feature: str
    label: str
    value: float
    contribution: float  # change in log-odds of default; positive raises risk
    text: str


class CounterfactualStep(Contract):
    """One achievable change that moves the applicant towards approval."""

    feature: str
    label: str
    current: float
    target: float
    text: str
    sufficient: bool  # True when this change alone would reach grade B


class RiskResult(Contract):
    model_version: str
    # SHA-256 of the exact artifact that scored the case; the version alone does not
    # change when a model is retrained under the same name.
    model_fingerprint: str | None = None
    probability_of_default: float = Field(ge=0, le=1)
    grade: RiskGrade
    recommendation: Literal["approve", "refer", "decline"]
    features: dict[str, float]
    reasons: list[ReasonCode]
    path_to_approval: list[CounterfactualStep]
    illustrative: bool = True  # trained on synthetic data until pilots produce outcomes


# --- Compliance --------------------------------------------------------------------------------


class FindingStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - a status, not a password
    FAIL = "fail"
    REVIEW = "review"  # a human must look; never an automatic rejection
    PENDING = "pending"  # depends on a later step, such as the officer's decision
    NOT_APPLICABLE = "not_applicable"


class Citation(Contract):
    source_id: str
    title: str
    clause: str
    url: str
    excerpt: str


class Finding(Contract):
    rule_id: str
    title: str
    status: FindingStatus
    severity: Literal["info", "minor", "major", "critical"]
    detail: str
    citations: list[Citation]


class ComplianceReport(Contract):
    jurisdiction: JurisdictionCode
    jurisdiction_name: str
    rule_pack_version: str
    findings: list[Finding]
    generated_at: Timestamp = Field(default_factory=utc_now)

    def count(self, status: FindingStatus) -> int:
        """Number of findings with the given status."""
        return sum(1 for f in self.findings if f.status == status)


# --- Case file ---------------------------------------------------------------------------------


class Applicant(Contract):
    full_name: str
    date_of_birth: date
    national_id: str
    phone: str
    business_name: str
    business_type: str
    years_in_business: float = Field(ge=0, le=100)
    preferred_language: str = "en"
    guarantor_name: str | None = None


class LoanRequest(Contract):
    amount: Money = Field(gt=0)
    currency: CurrencyCode
    tenor_months: int = Field(gt=0, le=120)
    annual_rate_pct: float = Field(ge=0, le=100)
    purpose: str


class Consent(Contract):
    given: bool
    recorded_at: Timestamp = Field(default_factory=utc_now)
    method: Literal["signature", "verbal_recorded", "digital"] = "digital"
    text_version: str = "consent-v1"


class Disclosure(Contract):
    """Loan terms shown to the borrower before signing, e.g. a Key Fact Statement."""

    apr_pct: float
    total_repayable: Money
    instalment: Money
    instalments: int
    issued_at: Timestamp = Field(default_factory=utc_now)
    acknowledged_at: Timestamp | None = None
    blank_fields: list[str] = []  # any unfilled field in the agreement presented for signature


class OfficerDecision(Contract):
    officer_id: str
    outcome: Literal["approve", "decline", "refer"]
    recommended: Literal["approve", "refer", "decline"]
    reason: str
    decided_at: Timestamp = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived(cls, data: Any) -> Any:
        """Accept stored JSON, which includes the derived `overridden` field."""
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "overridden"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overridden(self) -> bool:
        """Derived, so an override can never be recorded as agreement."""
        return self.outcome != self.recommended


class Explanation(Contract):
    """The borrower's explanation. The officer report is built on demand from the case."""

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_fields(cls, data: Any) -> Any:
        """Cases stored before `translated` was retired still load; `written_by` says it."""
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "translated"}
        return data

    borrower_text: str
    borrower_language: str
    english_text: str | None = None  # the same text in English, for the officer to check
    audio_available: bool = False
    written_by: str  # "<model>/<prompt version>", or "template" for the English fallback
    facts_digest: str = ""  # the facts, model and prompt it was written from


class CreditReview(Contract):
    """The lender's second pair of eyes: a loan officer sends the case to a reviewer."""

    reviewer_uid: str
    reviewer: str
    requested_by: str
    requested_at: Timestamp = Field(default_factory=utc_now)


class EvidenceRequest(Contract):
    """A question or request for evidence, from a lender or audit firm, until answered."""

    id: str = Field(default_factory=lambda: new_id("rq"))
    from_org_id: str
    requested_by: str
    addressed_to: Literal["lender", "business"]
    message: str = Field(min_length=1, max_length=2000)
    created_at: Timestamp = Field(default_factory=utc_now)
    answer: str | None = None
    answered_by: str | None = None
    answered_at: Timestamp | None = None


class AuditFinding(Contract):
    id: str = Field(default_factory=lambda: new_id("fd"))
    author: str
    severity: Literal["observation", "issue"]
    note: str = Field(min_length=1, max_length=2000)
    snapshot: str  # hash of the case as it was when the finding was written
    recorded_at: Timestamp = Field(default_factory=utc_now)


class Engagement(Contract):
    """An audit firm's work on one case: assigned to an audit officer, whose findings an
    audit reviewer approves as the final report or returns for more work."""

    id: str = Field(default_factory=lambda: new_id("en"))
    audit_firm_id: str
    assignee_uid: str
    assignee: str
    assigned_by: str
    assigned_at: Timestamp = Field(default_factory=utc_now)
    status: Literal["open", "submitted", "approved", "returned"] = "open"
    findings: list[AuditFinding] = []
    reviewed_by: str | None = None
    reviewed_at: Timestamp | None = None
    review_note: str | None = None
    report_snapshot: str | None = None  # the case as approved, when the report is final


class CaseStatus(StrEnum):
    DRAFT = "draft"
    ASSESSED = "assessed"
    DECIDED = "decided"


CaseId = Annotated[str, Field(pattern=f"^{CASE_ID_PATTERN}$")]


class CreditFile(Contract):
    """The full case: inputs, every agent's output and the officer's decision."""

    case_id: CaseId = Field(default_factory=lambda: new_id("case"))
    revision: int = Field(default=0, ge=0)  # bumped on every save; guards concurrent writers
    status: CaseStatus = CaseStatus.DRAFT
    created_at: Timestamp = Field(default_factory=utc_now)
    updated_at: Timestamp | None = None  # set by the repository on each save
    jurisdiction: JurisdictionCode
    applicant: Applicant
    loan: LoanRequest
    consent: Consent
    evidence: list[EvidenceDocument] = []
    extractions: list[ExtractionResult] = []
    cash_flow: CashFlowSummary | None = None
    consistency: ConsistencyReport | None = None
    risk: RiskResult | None = None
    compliance: ComplianceReport | None = None
    explanation: Explanation | None = None
    # Explanations already written from the current facts, by language, so switching
    # back to a language costs no model call.
    translations: dict[str, Explanation] = {}
    disclosure: Disclosure | None = None
    decision: OfficerDecision | None = None
    # Who may see the case. A lender's own case has no business; an owner's application
    # has no lender until the owner sends it to one.
    lender_org_id: str | None = None
    business_org_id: str | None = None
    credit_review: CreditReview | None = None
    requests: list[EvidenceRequest] = []
    engagements: list[Engagement] = []


# --- Organisations -----------------------------------------------------------------------------


class OrgType(StrEnum):
    PLATFORM = "platform"  # runs Ledger Lens; manages organisations, never sees cases
    LENDER = "lender"
    AUDIT_FIRM = "audit_firm"
    BUSINESS = "business"


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"  # approves organisations, platform settings, support
    ADMIN = "admin"  # an organisation's staff, roles and access; also does their work
    LOAN_OFFICER = "loan_officer"  # opens and prepares applications
    CREDIT_REVIEWER = "credit_reviewer"  # decides the applications assigned to them
    AUDIT_OFFICER = "audit_officer"  # works assigned engagements: requests and findings
    AUDIT_REVIEWER = "audit_reviewer"  # approves findings as the final report
    OWNER = "owner"  # the business profile, its evidence and who it is shared with
    ACCOUNTANT = "accountant"  # uploads records and answers requests for the owner


ROLES_BY_ORG_TYPE: dict[OrgType, frozenset[Role]] = {
    OrgType.PLATFORM: frozenset({Role.PLATFORM_ADMIN}),
    OrgType.LENDER: frozenset({Role.ADMIN, Role.LOAN_OFFICER, Role.CREDIT_REVIEWER}),
    OrgType.AUDIT_FIRM: frozenset({Role.ADMIN, Role.AUDIT_OFFICER, Role.AUDIT_REVIEWER}),
    OrgType.BUSINESS: frozenset({Role.OWNER, Role.ACCOUNTANT}),
}


class OrgStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"  # a lender or audit firm that registered itself, until approved
    SUSPENDED = "suspended"


ORG_ID_PATTERN = r"org_[a-z0-9_]{1,40}"


class Organisation(Contract):
    id: str = Field(default_factory=lambda: new_id("org"), pattern=f"^{ORG_ID_PATTERN}$")
    name: str = Field(min_length=1, max_length=120)
    type: OrgType
    jurisdiction: JurisdictionCode | None = None
    status: OrgStatus = OrgStatus.ACTIVE
    created_at: Timestamp = Field(default_factory=utc_now)


class Member(Contract):
    """A person's place in one organisation. `uid` is their Firebase Auth user id."""

    uid: str
    email: str
    display_name: str = ""
    org_id: str
    role: Role
    disabled: bool = False
    created_at: Timestamp = Field(default_factory=utc_now)


class GrantStatus(StrEnum):
    PENDING = "pending"  # asked of an audit firm, until its admin answers
    ACTIVE = "active"
    DECLINED = "declined"


class AccessGrant(Contract):
    """An organisation asks an audit firm to audit its cases, and the firm sees them once
    its admin accepts, until the grant is revoked; or it lets the platform's support see
    them until the grant expires."""

    id: str = Field(default_factory=lambda: new_id("gr"))
    grantor_org_id: str
    grantee_org_id: str
    granted_by: str
    granted_at: Timestamp = Field(default_factory=utc_now)
    status: GrantStatus = GrantStatus.ACTIVE  # grants stored before requests were active
    responded_by: str | None = None
    responded_at: Timestamp | None = None
    revoked_at: Timestamp | None = None
    revoked_by: str | None = None
    expires_at: Timestamp | None = None

    def live(self, now: datetime) -> bool:
        """Gives access now."""
        return (
            self.status is GrantStatus.ACTIVE
            and self.revoked_at is None
            and (self.expires_at is None or now < self.expires_at)
        )

    def open(self, now: datetime) -> bool:
        """Gives access now, or waits for an answer."""
        waiting = self.status is GrantStatus.PENDING and self.revoked_at is None
        return waiting or self.live(now)


class PlatformConfig(Contract):
    """Settings the platform admin changes at run time; None keeps the deployment's value."""

    daily_model_calls: int | None = Field(default=None, ge=0)
    self_registration: bool = True  # lenders and audit firms may apply to join
    updated_by: str | None = None
    updated_at: Timestamp | None = None
