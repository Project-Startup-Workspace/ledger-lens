"""Who may do what with a case. Every rule is here, so the API checks one place.

- A lender's members work the cases sent to that lender; only they acknowledge and decide.
- A business owner sees their own applications and prepares them until they are sent.
- An audit firm's members see, review and export the cases of organisations that
  granted the firm access, and only while the grant stands.
- The platform admin manages organisations and never sees a case.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ledger_lens.shared.schemas import (
    AccessGrant,
    CreditFile,
    Member,
    Organisation,
    OrgType,
    Role,
)


class Action(StrEnum):
    VIEW = "view"  # read the case, its evidence, report, audit trail; export a pack
    PREPARE = "prepare"  # upload evidence and assess
    EXPLAIN = "explain"  # write the borrower explanation in a language
    DECIDE = "decide"  # acknowledge the disclosure and record the decision
    REVIEW = "review"  # record an audit review


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
    def is_org_admin(self) -> bool:
        return self.role in (Role.ADMIN, Role.OWNER, Role.PLATFORM_ADMIN)

    def org_id(self) -> str:
        """The person's organisation; refused when they do not belong to one yet."""
        if self.org is None:
            raise AccessDeniedError("finish setting up your account first")
        return self.org.id


def lender_of(case: CreditFile, default_lender: str) -> str | None:
    """Cases created before organisations existed belong to the default lender."""
    if case.lender_org_id is None and case.business_org_id is None:
        return default_lender
    return case.lender_org_id


def grantors(grants: Iterable[AccessGrant]) -> set[str]:
    """Organisations whose grants still stand."""
    return {g.grantor_org_id for g in grants if g.revoked_at is None}


def allowed(
    who: Principal,
    action: Action,
    case: CreditFile,
    *,
    default_lender: str,
    granted_by: set[str] | frozenset[str] = frozenset(),
) -> bool:
    """Whether `who` may take `action` on `case`; `granted_by` are the organisations
    that granted `who`'s audit firm access."""
    if who.org is None:
        return False
    org = who.org
    lender = lender_of(case, default_lender)
    if org.type is OrgType.LENDER:
        return org.id == lender and action is not Action.REVIEW
    if org.type is OrgType.BUSINESS:
        if org.id != case.business_org_id:
            return False
        # Owners prepare until the application is sent. The explanation is written for
        # them, so they may ask for it in their language at any time.
        return action in (Action.VIEW, Action.EXPLAIN) or (
            action is Action.PREPARE and lender is None
        )
    if org.type is OrgType.AUDIT_FIRM:
        sources = {lender, case.business_org_id} - {None}
        return action in (Action.VIEW, Action.REVIEW) and bool(sources & set(granted_by))
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
        raise AccessDeniedError(f"you may not {action.value} this case")
