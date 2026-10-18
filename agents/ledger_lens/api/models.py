"""Request and response bodies that are specific to the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field

from ledger_lens.shared.schemas import (
    AccessGrant,
    Applicant,
    CaseStatus,
    JurisdictionCode,
    LoanRequest,
    Organisation,
    OrgType,
    Role,
)


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
    lender_org_id: str | None = None
    business_org_id: str | None = None


class ExplainRequest(BaseModel):
    language: str = Field(min_length=2, max_length=8)


class AcknowledgeDisclosure(BaseModel):
    blank_fields: list[str] = []


class DecisionRequest(BaseModel):
    """The deciding officer is taken from the authenticated request, not from this body."""

    outcome: Literal["approve", "decline", "refer"]
    reason: str = Field(min_length=1, max_length=2000)


class SendApplication(BaseModel):
    lender_org_id: str


class ReviewRequest(BaseModel):
    outcome: Literal["no_issues", "issues_found"]
    note: str = Field(min_length=1, max_length=2000)


class Me(BaseModel):
    """The signed-in person; `org` and `role` are empty until they join or register one."""

    uid: str
    email: str
    name: str
    org: Organisation | None
    role: Role | None
    organisations_enabled: bool


class RegisterBusiness(BaseModel):
    business_name: str = Field(min_length=1, max_length=120)
    jurisdiction: JurisdictionCode | None = None


class NewAccount(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=8, max_length=128)


class NewMember(NewAccount):
    role: Role


class NewOrganisation(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: OrgType
    jurisdiction: JurisdictionCode | None = None
    admin: NewAccount


class GrantRequest(BaseModel):
    audit_firm_id: str


class GrantView(AccessGrant):
    """A grant with both organisations' names, for display."""

    grantor_name: str
    grantee_name: str
