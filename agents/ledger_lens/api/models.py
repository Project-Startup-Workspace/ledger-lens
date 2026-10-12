"""Request and response bodies that are specific to the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field

from ledger_lens.shared.schemas import Applicant, CaseStatus, JurisdictionCode, LoanRequest


class CreateCase(BaseModel):
    applicant: Applicant
    loan: LoanRequest
    jurisdiction: JurisdictionCode
    consent_given: bool
    consent_method: Literal["signature", "verbal_recorded", "digital"] = "digital"


class CaseSummary(BaseModel):
    case_id: str
    status: CaseStatus
    business_name: str
    jurisdiction: str
    amount: float
    currency: str
    grade: str | None
    recommendation: str | None
    created_at: str


class ExplainRequest(BaseModel):
    language: str = Field(min_length=2, max_length=8)


class AcknowledgeDisclosure(BaseModel):
    blank_fields: list[str] = []


class DecisionRequest(BaseModel):
    officer_id: str = Field(min_length=1, max_length=64)
    outcome: Literal["approve", "decline", "refer"]
    reason: str = Field(min_length=1, max_length=2000)
