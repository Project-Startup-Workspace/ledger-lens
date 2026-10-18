"""Who may do what with a case. Every rule is here, so the API checks one place.

Lender: loan officers open and prepare applications and send them to a credit reviewer,
  who decides those assigned to them; the admin may do all of it.
Business: the owner prepares applications, sends them to a lender and acknowledges the
  terms; an accountant uploads records and answers requests, but never shares.
Audit firm: with a standing grant, the admin assigns engagements; the assigned audit
  officer requests evidence and records findings; an audit reviewer approves them.
Platform: never sees a case, unless an organisation grants time-limited support access.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ledger_lens.shared.schemas import (
    AccessGrant,
    CreditFile,
    Engagement,
    Member,
    Organisation,
    OrgStatus,
    OrgType,
    Role,
    utc_now,
)


class Action(StrEnum):
    VIEW = "view"  # read the case, its evidence, report and audit trail; export a pack
    UPLOAD = "upload"  # add evidence
    PREPARE = "prepare"  # assess
    EXPLAIN = "explain"  # write the borrower explanation in a language
    ACKNOWLEDGE = "acknowledge"  # record that the borrower read the loan terms
    SEND = "send"  # the owner sends the application to a lender
    ASSIGN_REVIEWER = "assign_reviewer"  # send the case to a credit reviewer
    DECIDE = "decide"
    REQUEST = "request"  # ask for evidence or an explanation
    ANSWER_LENDER = "answer_lender"  # answer a request addressed to the lender
    ANSWER_BUSINESS = "answer_business"  # answer a request addressed to the business
    ASSIGN_ENGAGEMENT = "assign_engagement"
    RECORD_FINDINGS = "record_findings"
    APPROVE_REPORT = "approve_report"


class AccessDeniedError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    """The signed-in person and, once they belong to one, their organisation."""

    uid: str
    email: str
    name: str = ""
    member: Member | None = None
    org: Organisation | None = None

    @property
    def actor(self) -> str:
        """How the person appears in the audit trail."""
        return self.email

    @property
    def org_type(self) -> OrgType | None:
        return self.org.type if self.org else None

    @property
    def role(self) -> Role | None:
        return self.member.role if self.member else None

    @property
    def active(self) -> bool:
        return self.org is not None and self.org.status is OrgStatus.ACTIVE

    @property
    def is_org_admin(self) -> bool:
        return self.role in (Role.ADMIN, Role.OWNER)

    def has(self, *roles: Role) -> bool:
        return self.role in roles

    def org_id(self) -> str:
        """The person's active organisation; refused otherwise."""
        if self.org is None:
            raise AccessDeniedError("finish setting up your account first")
        if self.org.status is OrgStatus.PENDING:
            raise AccessDeniedError("your organisation is waiting for the platform's approval")
        if self.org.status is OrgStatus.SUSPENDED:
            raise AccessDeniedError("your organisation is suspended; contact the platform")
        return self.org.id


def lender_of(case: CreditFile, default_lender: str) -> str | None:
    """Cases created before organisations existed belong to the default lender."""
    if case.lender_org_id is None and case.business_org_id is None:
        return default_lender
    return case.lender_org_id


def grantors(grants: Iterable[AccessGrant], now: datetime | None = None) -> set[str]:
    """Organisations whose grants still stand."""
    moment = now or utc_now()
    return {g.grantor_org_id for g in grants if g.live(moment)}


def my_engagement(who: Principal, case: CreditFile) -> Engagement | None:
    """The engagement on this case assigned to `who`, if any."""
    return next((e for e in case.engagements if e.assignee_uid == who.uid), None)


def firm_engagements(who: Principal, case: CreditFile) -> list[Engagement]:
    return [e for e in case.engagements if who.org and e.audit_firm_id == who.org.id]


def open_requests(case: CreditFile, addressed_to: str) -> bool:
    return any(r.answer is None and r.addressed_to == addressed_to for r in case.requests)


def allowed(
    who: Principal,
    action: Action,
    case: CreditFile,
    *,
    default_lender: str,
    granted_by: set[str] | frozenset[str] = frozenset(),
) -> bool:
    """Whether `who` may take `action` on `case`; `granted_by` are the organisations
    whose grants to `who`'s organisation stand."""
    if who.org is None or not who.active:
        return False
    org, lender = who.org, lender_of(case, default_lender)
    sources = {lender, case.business_org_id} - {None}
    if org.type is OrgType.LENDER:
        if org.id != lender:
            return False
        admin, officer = who.has(Role.ADMIN), who.has(Role.LOAN_OFFICER)
        assigned = case.credit_review is not None and case.credit_review.reviewer_uid == who.uid
        return {
            Action.VIEW: True,
            Action.EXPLAIN: True,
            Action.REQUEST: True,
            Action.ANSWER_LENDER: True,
            Action.UPLOAD: admin or officer,
            Action.PREPARE: admin or officer,
            Action.ACKNOWLEDGE: admin or officer,
            Action.ASSIGN_REVIEWER: admin or officer,
            Action.DECIDE: admin or (who.has(Role.CREDIT_REVIEWER) and assigned),
        }.get(action, False)
    if org.type is OrgType.BUSINESS:
        if org.id != case.business_org_id:
            return False
        owner, unsent = who.has(Role.OWNER), lender is None
        return {
            Action.VIEW: True,
            Action.EXPLAIN: True,
            Action.ANSWER_BUSINESS: True,
            # Before it is sent the business prepares freely; afterwards it only adds
            # evidence to answer a request, and the lender reassesses.
            Action.UPLOAD: unsent or open_requests(case, "business"),
            Action.PREPARE: unsent,
            Action.ACKNOWLEDGE: owner,
            Action.SEND: owner and unsent,
        }.get(action, False)
    if org.type is OrgType.AUDIT_FIRM:
        if not sources & set(granted_by):
            return False
        mine = my_engagement(who, case)
        working = mine is not None and mine.status in ("open", "returned")
        submitted = any(e.status == "submitted" for e in firm_engagements(who, case))
        return {
            # Audit officers see the cases assigned to them; the admin and reviewers see all.
            Action.VIEW: who.has(Role.ADMIN, Role.AUDIT_REVIEWER) or mine is not None,
            Action.ASSIGN_ENGAGEMENT: who.has(Role.ADMIN),
            Action.REQUEST: working,
            Action.RECORD_FINDINGS: working,
            Action.APPROVE_REPORT: who.has(Role.ADMIN, Role.AUDIT_REVIEWER) and submitted,
        }.get(action, False)
    if org.type is OrgType.PLATFORM:
        return action is Action.VIEW and bool(sources & set(granted_by))
    return False


def require(
    who: Principal,
    action: Action,
    case: CreditFile,
    *,
    default_lender: str,
    granted_by: set[str] | frozenset[str] = frozenset(),
) -> None:
    if not allowed(who, action, case, default_lender=default_lender, granted_by=granted_by):
        raise AccessDeniedError(f"you may not {action.value.replace('_', ' ')} on this case")
