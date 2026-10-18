"""Organisations, members and access grants, with every change in the organisation's own
audit chain (keyed by its id, beside the case chains).

Run `python -m ledger_lens.organisations --help` for the set-up commands.
"""

import argparse
import getpass
import threading
import time
from collections.abc import Callable
from typing import Any

from ledger_lens.access import AccessDeniedError, Principal, grantors
from ledger_lens.audit_trail.chain import AuditStore
from ledger_lens.shared.directory import Directory
from ledger_lens.shared.identity import IdentityProvider, SignedIn
from ledger_lens.shared.schemas import (
    ROLES_BY_ORG_TYPE,
    AccessGrant,
    Member,
    Organisation,
    OrgType,
    Role,
    utc_now,
)

PLATFORM_ORG = "org_platform"
MEMBER_CACHE_S = 30.0  # a removed member loses access within this time on every instance
MIN_PASSWORD = 8


class SetupError(ValueError):
    """The request does not fit the directory, e.g. a role the organisation cannot have."""


class Organisations:
    def __init__(
        self,
        directory: Directory,
        identity: IdentityProvider | None,
        audit: AuditStore,
        default_lender: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._d = directory
        self._identity = identity
        self._audit = audit
        self.default_lender = default_lender
        self._clock = clock
        self._cache: dict[str, tuple[float, Principal]] = {}
        self._cache_guard = threading.Lock()

    @property
    def identity(self) -> IdentityProvider | None:
        return self._identity

    @property
    def enabled(self) -> bool:
        """False when sign-in is the single-lender kind and organisations are not used."""
        return self._identity is not None

    # --- Who is signed in -------------------------------------------------------------

    def principal(self, signed: SignedIn) -> Principal:
        """The person with their membership, from a short cache; a disabled member is
        treated as not belonging to any organisation."""
        now = self._clock()
        with self._cache_guard:
            hit = self._cache.get(signed.uid)
        if hit and now - hit[0] < MEMBER_CACHE_S:
            return hit[1]
        member = self._d.get_member(signed.uid)
        if member is not None and member.disabled:
            member = None
        org = self._d.get_org(member.org_id) if member else None
        who = Principal(signed.uid, signed.email, signed.name, member, org)
        with self._cache_guard:
            self._cache[signed.uid] = (now, who)
        return who

    def single_lender_principal(self, name: str) -> Principal:
        """Single-lender sign-in: everyone is an officer of the default lender."""
        org = Organisation(id=self.default_lender, name="Default lender", type=OrgType.LENDER)
        member = Member(uid=name, email=name, org_id=org.id, role=Role.OFFICER)
        return Principal(name, name, name, member, org)

    def granted_by(self, who: Principal) -> set[str]:
        """Organisations that let `who`'s audit firm see their cases."""
        if who.org_type is not OrgType.AUDIT_FIRM:
            return set()
        return grantors(self._d.list_grants(grantee_org_id=who.org_id()))

    # --- Organisations and members ----------------------------------------------------

    def register_business(
        self, who: Principal, *, business_name: str, jurisdiction: str | None
    ) -> Principal:
        """A newly signed-up person creates their business and becomes its owner."""
        self._need_identity()
        if who.member is not None:
            raise SetupError("this account already belongs to an organisation")
        org = Organisation(
            name=business_name.strip(), type=OrgType.BUSINESS, jurisdiction=jurisdiction
        )
        self._d.save_org(org)
        self._record(org.id, "organisation_created", who, {"name": org.name, "type": org.type})
        member = Member(
            uid=who.uid, email=who.email, display_name=who.name, org_id=org.id, role=Role.OWNER
        )
        self._join(member, who)
        return Principal(who.uid, who.email, who.name, member, org)

    def create_organisation(
        self,
        who: Principal,
        *,
        name: str,
        org_type: OrgType,
        jurisdiction: str | None,
        admin_email: str,
        admin_name: str,
        admin_password: str,
    ) -> Organisation:
        """The platform admin adds a lender or audit firm together with its first admin."""
        self._require_role(who, Role.PLATFORM_ADMIN)
        if org_type not in (OrgType.LENDER, OrgType.AUDIT_FIRM):
            raise SetupError("only lenders and audit firms are created here")
        org = Organisation(name=name.strip(), type=org_type, jurisdiction=jurisdiction)
        self._d.save_org(org)
        self._record(org.id, "organisation_created", who, {"name": org.name, "type": org.type})
        self._add(who, org, admin_email, admin_name, admin_password, Role.ADMIN)
        return org

    def add_member(
        self, who: Principal, *, email: str, display_name: str, password: str, role: Role
    ) -> Member:
        """An organisation's admin adds a colleague with a starting password."""
        org = self._admin_org(who)
        return self._add(who, org, email, display_name, password, role)

    def remove_member(self, who: Principal, uid: str) -> Member:
        org = self._admin_org(who)
        member = self._d.get_member(uid)
        if member is None or member.org_id != org.id:
            raise LookupError(uid)
        if uid == who.uid:
            raise SetupError("you cannot remove yourself")
        assert self._identity is not None
        self._identity.disable(uid)
        member = member.model_copy(update={"disabled": True})
        self._d.save_member(member)
        self._forget(uid)
        self._record(org.id, "member_removed", who, {"uid": uid, "role": member.role})
        return member

    def members(self, who: Principal) -> list[Member]:
        return self._d.list_members(self._admin_org(who).id)

    def organisations(self, who: Principal, org_type: OrgType | None = None) -> list[Organisation]:
        """The platform admin sees every organisation; others see lenders and audit firms,
        the organisations they can send applications to or grant access to."""
        if who.role is Role.PLATFORM_ADMIN:
            return self._d.list_orgs(org_type)
        who.org_id()
        public = (OrgType.LENDER, OrgType.AUDIT_FIRM)
        if org_type is not None and org_type not in public:
            raise AccessDeniedError("you may list lenders and audit firms only")
        return [o for t in ([org_type] if org_type else public) for o in self._d.list_orgs(t)]

    def organisation(self, org_id: str) -> Organisation | None:
        return self._d.get_org(org_id)

    # --- Access grants ----------------------------------------------------------------

    def grant(self, who: Principal, audit_firm_id: str) -> AccessGrant:
        """A lender or business admin lets an audit firm see the organisation's cases."""
        org = self._admin_org(who)
        if org.type not in (OrgType.LENDER, OrgType.BUSINESS):
            raise SetupError("only lenders and businesses grant access")
        firm = self._d.get_org(audit_firm_id)
        if firm is None or firm.type is not OrgType.AUDIT_FIRM:
            raise SetupError("access can be granted to audit firms only")
        live = self._d.list_grants(grantor_org_id=org.id, grantee_org_id=firm.id)
        if existing := next((g for g in live if g.revoked_at is None), None):
            return existing
        grant = AccessGrant(grantor_org_id=org.id, grantee_org_id=firm.id, granted_by=who.actor)
        self._d.save_grant(grant)
        payload = {"grant": grant.id, "audit_firm": firm.id}
        self._record(org.id, "access_granted", who, payload)
        self._record(firm.id, "access_received", who, payload | {"from": org.id})
        return grant

    def revoke(self, who: Principal, grant_id: str) -> AccessGrant:
        org = self._admin_org(who)
        grant = self._d.get_grant(grant_id)
        if grant is None or grant.grantor_org_id != org.id:
            raise LookupError(grant_id)
        if grant.revoked_at is not None:
            return grant
        grant = grant.model_copy(update={"revoked_at": utc_now(), "revoked_by": who.actor})
        self._d.save_grant(grant)
        payload = {"grant": grant.id, "audit_firm": grant.grantee_org_id}
        self._record(org.id, "access_revoked", who, payload)
        self._record(grant.grantee_org_id, "access_withdrawn", who, payload | {"from": org.id})
        return grant

    def grants(self, who: Principal) -> list[AccessGrant]:
        """Grants this organisation gave, or (for an audit firm) received."""
        org_id = who.org_id()
        if who.org_type is OrgType.AUDIT_FIRM:
            return self._d.list_grants(grantee_org_id=org_id)
        return self._d.list_grants(grantor_org_id=org_id)

    def events(self, who: Principal) -> list[dict[str, Any]]:
        """The organisation's own audit chain, for its admin."""
        org = self._admin_org(who)
        return [e.model_dump(mode="json") for e in self._audit.events(org.id)]

    # --- Set-up -----------------------------------------------------------------------

    def ensure_platform_admin(self, email: str, display_name: str, password: str) -> Member:
        """Create the platform organisation and its admin; run once from the command line."""
        if self._d.get_org(PLATFORM_ORG) is None:
            self._d.save_org(
                Organisation(id=PLATFORM_ORG, name="Ledger Lens", type=OrgType.PLATFORM)
            )
        system = Principal("system", "system")
        org = self._d.get_org(PLATFORM_ORG)
        assert org is not None
        return self._add(system, org, email, display_name, password, Role.PLATFORM_ADMIN)

    def ensure_organisation(self, org: Organisation) -> Organisation:
        """Create an organisation with a fixed id (the default lender) if it is missing."""
        existing = self._d.get_org(org.id)
        if existing is not None:
            return existing
        self._d.save_org(org)
        system = Principal("system", "system")
        self._record(org.id, "organisation_created", system, {"name": org.name, "type": org.type})
        return org

    def add_to(
        self, org_id: str, *, email: str, display_name: str, password: str, role: Role
    ) -> Member:
        """Add a member to any organisation; for the set-up commands only."""
        org = self._d.get_org(org_id)
        if org is None:
            raise LookupError(org_id)
        return self._add(Principal("system", "system"), org, email, display_name, password, role)

    # --- Internals --------------------------------------------------------------------

    def _add(
        self,
        who: Principal,
        org: Organisation,
        email: str,
        display_name: str,
        password: str,
        role: Role,
    ) -> Member:
        identity = self._need_identity()
        if role not in ROLES_BY_ORG_TYPE[org.type]:
            raise SetupError(f"a {org.type.value} cannot have the role {role.value}")
        if len(password) < MIN_PASSWORD:
            raise SetupError(f"the password needs at least {MIN_PASSWORD} characters")
        email = email.strip().lower()
        uid = identity.create_account(email, password, display_name.strip())
        member = Member(
            uid=uid, email=email, display_name=display_name.strip(), org_id=org.id, role=role
        )
        self._join(member, who)
        return member

    def _join(self, member: Member, who: Principal) -> None:
        assert self._identity is not None
        self._d.save_member(member)
        org = self._d.get_org(member.org_id)
        assert org is not None
        self._identity.set_claims(
            member.uid, {"org_id": org.id, "org_type": org.type.value, "role": member.role.value}
        )
        self._forget(member.uid)
        self._record(org.id, "member_added", who, {"uid": member.uid, "role": member.role})

    def _admin_org(self, who: Principal) -> Organisation:
        self._need_identity()
        if not who.is_org_admin or who.org is None or who.org_type is OrgType.PLATFORM:
            raise AccessDeniedError("only the organisation's admin may do this")
        return who.org

    @staticmethod
    def _require_role(who: Principal, role: Role) -> None:
        if who.role is not role:
            raise AccessDeniedError(f"only a {role.value} may do this")

    def _need_identity(self) -> IdentityProvider:
        if self._identity is None:
            raise SetupError("organisations need Firebase sign-in (LL_IDENTITY_BACKEND=gcp)")
        return self._identity

    def _forget(self, uid: str) -> None:
        with self._cache_guard:
            self._cache.pop(uid, None)

    def _record(self, org_id: str, event: str, who: Principal, payload: dict[str, Any]) -> None:
        self._audit.append(org_id, event, who.actor, payload)


def main(argv: list[str] | None = None) -> None:
    """Set-up commands, run with the deployment's settings (LL_* variables)."""
    from ledger_lens.audit_trail.stores import build_audit_store
    from ledger_lens.shared.config import get_settings
    from ledger_lens.shared.directory import build_directory
    from ledger_lens.shared.identity import build_identity
    from ledger_lens.shared.storage import build_case_repository

    parser = argparse.ArgumentParser(prog="python -m ledger_lens.organisations")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("platform-admin", help="create the platform admin account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Platform admin")
    member = commands.add_parser("add-member", help="add an account to an organisation")
    member.add_argument("--org", required=True)
    member.add_argument("--email", required=True)
    member.add_argument("--name", default="")
    member.add_argument("--role", required=True, choices=[r.value for r in Role])
    lender = commands.add_parser(
        "default-lender", help="create the default lender and move older cases to it"
    )
    lender.add_argument("--name", required=True)
    add_org = commands.add_parser("add-org", help="create a lender or audit firm")
    add_org.add_argument("--name", required=True)
    add_org.add_argument("--type", required=True, choices=[OrgType.LENDER, OrgType.AUDIT_FIRM])
    add_org.add_argument("--jurisdiction")
    args = parser.parse_args(argv)

    settings = get_settings()
    audit = build_audit_store(settings)
    orgs = Organisations(
        build_directory(settings), build_identity(settings), audit, settings.default_lender_org
    )
    if args.command == "default-lender":
        org = orgs.ensure_organisation(
            Organisation(id=settings.default_lender_org, name=args.name, type=OrgType.LENDER)
        )
        cases = build_case_repository(settings)
        moved = 0
        for case in cases.list(10_000):
            if case.lender_org_id is None and case.business_org_id is None:
                case.lender_org_id = org.id
                cases.save(case)
                audit.append(case.case_id, "lender_assigned", "system", {"lender": org.id})
                moved += 1
        print(f"{org.id}: {org.name}; {moved} older cases moved to it")
        return
    if args.command == "add-org":
        made_org = orgs.ensure_organisation(
            Organisation(name=args.name, type=OrgType(args.type), jurisdiction=args.jurisdiction)
        )
        print(f"{made_org.id}: {made_org.name}")
        return
    password = getpass.getpass("Password for the new account: ")
    if args.command == "platform-admin":
        made = orgs.ensure_platform_admin(args.email, args.name, password)
    else:
        made = orgs.add_to(
            args.org,
            email=args.email,
            display_name=args.name,
            password=password,
            role=Role(args.role),
        )
    print(f"{made.email}: {made.role.value} of {made.org_id}")


if __name__ == "__main__":
    main()
