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
    OrgStatus,
    OrgType,
    PlatformConfig,
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
    reviewer: str | None = None  # the credit reviewer the case is assigned to
    open_requests: int = 0
    engagements: list[str] = []  # each engagement's status


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


class AssignReviewer(BaseModel):
    reviewer_uid: str


class NewRequest(BaseModel):
    addressed_to: Literal["lender", "business"]
    message: str = Field(min_length=1, max_length=2000)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class AssignEngagement(BaseModel):
    assignee_uid: str


class NewFinding(BaseModel):
    severity: Literal["observation", "issue"]
    note: str = Field(min_length=1, max_length=2000)


class EngagementReview(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)


class Me(BaseModel):
    """The signed-in person; `org` and `role` are empty until they join or register one."""

    uid: str
    email: str
    name: str
    org: Organisation | None
    role: Role | None
    organisations_enabled: bool


class RegisterOrganisation(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: OrgType = OrgType.BUSINESS
    jurisdiction: JurisdictionCode | None = None


class StatusChange(BaseModel):
    status: OrgStatus


class RoleChange(BaseModel):
    role: Role


class SettingsChange(BaseModel):
    daily_model_calls: int | None = Field(default=None, ge=0, le=100_000)
    self_registration: bool | None = None


class PlatformSettings(BaseModel):
    config: PlatformConfig
    deployment_daily_model_calls: int
    effective_daily_model_calls: int  # 0 means no cap
    model_calls_today: int | None  # None when calls are not counted (offline models)
    llm_provider: str
    model_extract: str
    model_reason: str


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
    grantee_org_id: str  # an audit firm, or the platform for a day of support access


class GrantView(AccessGrant):
    """A grant with both organisations' names, for display."""

    grantor_name: str
    grantee_name: str
