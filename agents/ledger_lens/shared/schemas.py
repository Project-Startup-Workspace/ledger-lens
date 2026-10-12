"""Pydantic contracts passed between agents, stored in case files and served by the API.

Agents never import each other's internals; they exchange only these models.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    model_validator,
)

# Money is exact in memory and a plain number in JSON, so charts need no parsing.
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
    uploaded_at: datetime = Field(default_factory=utc_now)


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

    currency: str
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
    generated_at: datetime = Field(default_factory=utc_now)

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
    years_in_business: float = Field(ge=0)
    preferred_language: str = "en"
    guarantor_name: str | None = None


class LoanRequest(Contract):
    amount: Money = Field(gt=0)
    currency: str
    tenor_months: int = Field(gt=0, le=120)
    annual_rate_pct: float = Field(ge=0, le=100)
    purpose: str


class Consent(Contract):
    given: bool
    recorded_at: datetime = Field(default_factory=utc_now)
    method: Literal["signature", "verbal_recorded", "digital"] = "digital"
    text_version: str = "consent-v1"


class Disclosure(Contract):
    """Loan terms shown to the borrower before signing, e.g. a Key Fact Statement."""

    apr_pct: float
    total_repayable: Money
    instalment: Money
    instalments: int
    issued_at: datetime = Field(default_factory=utc_now)
    acknowledged_at: datetime | None = None
    blank_fields: list[str] = []  # any unfilled field in the agreement presented for signature


class OfficerDecision(Contract):
    officer_id: str
    outcome: Literal["approve", "decline", "refer"]
    recommended: Literal["approve", "refer", "decline"]
    reason: str
    decided_at: datetime = Field(default_factory=utc_now)

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

    borrower_text: str
    borrower_language: str
    translated: bool  # False when the borrower text fell back to the English template
    audio_available: bool = False
    written_by: str  # "<model>/<prompt version>", or "template"


class CaseStatus(StrEnum):
    DRAFT = "draft"
    ASSESSED = "assessed"
    DECIDED = "decided"


CaseId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class CreditFile(Contract):
    """The full case: inputs, every agent's output and the officer's decision."""

    case_id: CaseId = Field(default_factory=lambda: new_id("case"))
    revision: int = Field(default=0, ge=0)  # bumped on every save; guards concurrent writers
    status: CaseStatus = CaseStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
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
    disclosure: Disclosure | None = None
    decision: OfficerDecision | None = None
