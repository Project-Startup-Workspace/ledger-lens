"""Organisations and roles through the API, with Firebase replaced by an in-memory fake."""

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from ledger_lens.api.app import create_app
from ledger_lens.audit_trail.chain import AuditStore
from ledger_lens.audit_trail.stores import build_audit_store
from ledger_lens.shared.config import Settings
from ledger_lens.shared.identity import AccountExistsError, InvalidTokenError, SignedIn

DEMO = "synthetic-grocer-kandy"


@dataclass
class FakeIdentity:
    """Accounts in memory; an account's ID token is its uid."""

    accounts: dict[str, tuple[str, str]] = field(default_factory=dict)  # uid -> (email, name)
    claims: dict[str, dict[str, str]] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)

    def sign_up(self, email: str, name: str = "") -> str:
        uid = f"uid{len(self.accounts)}"
        self.accounts[uid] = (email, name)
        return uid

    def verify(self, id_token: str) -> SignedIn:
        if id_token not in self.accounts or id_token in self.disabled:
            raise InvalidTokenError("unknown")
        email, name = self.accounts[id_token]
        return SignedIn(uid=id_token, email=email, name=name)

    def create_account(self, email: str, password: str, display_name: str) -> str:
        if any(e == email for e, _ in self.accounts.values()):
            raise AccountExistsError(email)
        return self.sign_up(email, display_name)

    def set_claims(self, uid: str, claims: dict[str, str]) -> None:
        self.claims[uid] = claims

    def disable(self, uid: str) -> None:
        self.disabled.add(uid)


@pytest.fixture
def identity() -> FakeIdentity:
    return FakeIdentity()


@pytest.fixture
def client(settings: Settings, identity: FakeIdentity) -> TestClient:
    return TestClient(create_app(settings, identity=identity))


def as_(uid: str) -> dict[str, str]:
    return {"x-ll-id-token": uid}


def uid_of(identity: FakeIdentity, email: str) -> str:
    return next(uid for uid, (e, _) in identity.accounts.items() if e == email)


@pytest.fixture
def world(client: TestClient, identity: FakeIdentity, settings: Settings) -> dict[str, str]:
    """A platform admin, two lenders, an audit firm and their people."""
    from ledger_lens.organisations import Organisations
    from ledger_lens.shared.directory import build_directory

    orgs = Organisations(
        build_directory(settings),
        identity,
        _audit(settings),
        settings.default_lender_org,
    )
    orgs.ensure_platform_admin("root@ll.test", "Root", "password1")
    root = uid_of(identity, "root@ll.test")

    def create(name: str, kind: str, admin: str) -> str:
        body = {
            "name": name,
            "type": kind,
            "admin": {"email": admin, "display_name": name, "password": "password1"},
        }
        response = client.post("/organisations", json=body, headers=as_(root))
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    ids = {
        "root": root,
        "lender": create("Lanka Micro", "lender", "admin@lanka.test"),
        "other_lender": create("Other Bank", "lender", "admin@other.test"),
        "firm": create("Clear Audit", "audit_firm", "admin@clear.test"),
    }
    for who in ("admin@lanka.test", "admin@other.test", "admin@clear.test"):
        ids[who] = uid_of(identity, who)
    added = client.post(
        "/members",
        json={"email": "auditor@clear.test", "password": "password1", "role": "auditor"},
        headers=as_(ids["admin@clear.test"]),
    )
    assert added.status_code == 201
    ids["auditor"] = added.json()["uid"]
    return ids


def _audit(settings: Settings) -> AuditStore:
    return build_audit_store(settings)


def owner_with_application(client: TestClient, identity: FakeIdentity) -> tuple[str, str]:
    """A signed-up owner registers their business and opens an application."""
    uid = identity.sign_up("selvi@shop.test", "Selvi")
    me = client.get("/me", headers=as_(uid)).json()
    assert me["org"] is None and me["organisations_enabled"]
    registered = client.post(
        "/me/business", json={"business_name": "Selvi Stores"}, headers=as_(uid)
    )
    assert registered.json()["role"] == "owner"
    assert identity.claims[uid]["org_type"] == "business"
    body = {
        "applicant": {
            "full_name": "Selvi K",
            "date_of_birth": "1985-02-01",
            "national_id": "850321234V",
            "phone": "+94770000000",
            "business_name": "Selvi Stores",
            "business_type": "grocery",
            "years_in_business": 6,
        },
        "loan": {
            "amount": 150000,
            "currency": "LKR",
            "tenor_months": 12,
            "annual_rate_pct": 24,
            "purpose": "stock",
        },
        "jurisdiction": "lk",
        "consent_given": True,
    }
    case = client.post("/cases", json=body, headers=as_(uid))
    assert case.status_code == 201, case.text
    return uid, case.json()["case_id"]


def test_sign_in_is_required(client: TestClient) -> None:
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers=as_("forged")).status_code == 401


def test_owner_prepares_privately_then_sends_to_one_lender(
    client: TestClient, identity: FakeIdentity, world: dict[str, str]
) -> None:
    owner, case_id = owner_with_application(client, identity)
    lender, other = world["admin@lanka.test"], world["admin@other.test"]
    notebook = ("p1.png", b"\x89PNG fake", "image/png")
    upload = client.post(
        f"/cases/{case_id}/evidence",
        data={"kind": "notebook"},
        files={"file": notebook},
        headers=as_(owner),
    )
    assert upload.status_code == 201
    assert client.get(f"/cases/{case_id}", headers=as_(lender)).status_code == 404

    lenders = client.get("/organisations?type=lender", headers=as_(owner)).json()
    assert {o["name"] for o in lenders} == {"Lanka Micro", "Other Bank"}
    sent = client.post(
        f"/cases/{case_id}/send", json={"lender_org_id": world["lender"]}, headers=as_(owner)
    )
    assert sent.json()["lender_org_id"] == world["lender"]
    again = client.post(
        f"/cases/{case_id}/send", json={"lender_org_id": world["other_lender"]}, headers=as_(owner)
    )
    assert again.status_code == 403

    assert client.get(f"/cases/{case_id}", headers=as_(lender)).status_code == 200
    assert [c["case_id"] for c in client.get("/cases", headers=as_(lender)).json()] == [case_id]
    assert client.get(f"/cases/{case_id}", headers=as_(other)).status_code == 404
    assert client.get("/cases", headers=as_(other)).json() == []
    # Sent: the owner still sees it but no longer changes it, and never decides.
    assert client.get(f"/cases/{case_id}", headers=as_(owner)).status_code == 200
    late = client.post(
        f"/cases/{case_id}/evidence",
        data={"kind": "notebook"},
        files={"file": ("p2.png", b"\x89PNG other", "image/png")},
        headers=as_(owner),
    )
    assert late.status_code == 403
    decide = {"outcome": "approve", "reason": "mine"}
    assert (
        client.post(f"/cases/{case_id}/decision", json=decide, headers=as_(owner)).status_code
        == 403
    )
    events = client.get(f"/cases/{case_id}/audit", headers=as_(owner)).json()["events"]
    assert events[-1]["event_type"] == "application_sent"
    assert events[-1]["actor"] == "selvi@shop.test"


def test_audit_firm_sees_cases_only_while_granted(
    client: TestClient, identity: FakeIdentity, world: dict[str, str]
) -> None:
    lender_admin, auditor = world["admin@lanka.test"], world["auditor"]
    case_id = client.post(f"/demo-cases/{DEMO}", headers=as_(lender_admin)).json()["case_id"]
    assert client.post(f"/cases/{case_id}/assess", headers=as_(lender_admin)).status_code == 200
    assert client.get(f"/cases/{case_id}", headers=as_(auditor)).status_code == 404
    assert client.get("/cases", headers=as_(auditor)).json() == []

    grant = client.post(
        "/grants", json={"audit_firm_id": world["firm"]}, headers=as_(lender_admin)
    ).json()
    received = client.get("/grants", headers=as_(auditor)).json()
    assert received[0]["id"] == grant["id"] and received[0]["grantor_name"] == "Lanka Micro"
    assert [c["case_id"] for c in client.get("/cases", headers=as_(auditor)).json()] == [case_id]
    assert client.post(f"/cases/{case_id}/assess", headers=as_(auditor)).status_code == 403
    reviewed = client.post(
        f"/cases/{case_id}/reviews",
        json={"outcome": "no_issues", "note": "Evidence matches the wallet."},
        headers=as_(auditor),
    ).json()
    assert reviewed["reviews"][0]["reviewer"] == "auditor@clear.test"
    assert client.post(f"/cases/{case_id}/audit-pack", headers=as_(auditor)).status_code == 200
    assert (
        client.post(
            f"/cases/{case_id}/reviews",
            json={"outcome": "no_issues", "note": "x"},
            headers=as_(lender_admin),
        ).status_code
        == 403
    )

    client.post(f"/grants/{grant['id']}/revoke", headers=as_(lender_admin))
    assert client.get(f"/cases/{case_id}", headers=as_(auditor)).status_code == 404
    org_log = client.get("/organisation/audit", headers=as_(lender_admin)).json()
    assert org_log["verification"]["valid"]
    assert [e["event_type"] for e in org_log["events"]][-2:] == ["access_granted", "access_revoked"]


def test_roles_are_checked_against_the_organisation(
    client: TestClient, identity: FakeIdentity, world: dict[str, str]
) -> None:
    lender_admin = world["admin@lanka.test"]
    wrong_role = {"email": "x@lanka.test", "password": "password1", "role": "auditor"}
    assert client.post("/members", json=wrong_role, headers=as_(lender_admin)).status_code == 422
    officer = client.post(
        "/members",
        json={"email": "officer@lanka.test", "password": "password1", "role": "officer"},
        headers=as_(lender_admin),
    ).json()
    duplicate = {"email": "officer@lanka.test", "password": "password1", "role": "officer"}
    assert client.post("/members", json=duplicate, headers=as_(lender_admin)).status_code == 409
    as_officer = as_(officer["uid"])
    assert client.get("/members", headers=as_officer).status_code == 403
    assert client.post(f"/demo-cases/{DEMO}", headers=as_officer).status_code == 201
    # The platform admin manages organisations and never sees a case.
    assert client.get("/cases", headers=as_(world["root"])).status_code == 403
    assert client.post(f"/demo-cases/{DEMO}", headers=as_(world["root"])).status_code == 403
    body = {"name": "Shop", "type": "business", "admin": duplicate}
    assert client.post("/organisations", json=body, headers=as_(lender_admin)).status_code == 403

    removed = client.post(f"/members/{officer['uid']}/remove", headers=as_(lender_admin))
    assert removed.json()["disabled"] is True
    assert client.get("/cases", headers=as_officer).status_code == 401
    assert (
        client.post(f"/members/{lender_admin}/remove", headers=as_(lender_admin)).status_code == 422
    )


def test_a_member_cannot_register_a_second_organisation(
    client: TestClient, world: dict[str, str]
) -> None:
    again = client.post(
        "/me/business", json={"business_name": "Side shop"}, headers=as_(world["auditor"])
    )
    assert again.status_code == 422


def test_cases_from_before_organisations_belong_to_the_default_lender(
    settings: Settings, identity: FakeIdentity
) -> None:
    from ledger_lens.organisations import Organisations
    from ledger_lens.shared.directory import build_directory
    from ledger_lens.shared.schemas import Organisation, OrgType, Role

    legacy_id = TestClient(create_app(settings)).post(f"/demo-cases/{DEMO}").json()["case_id"]
    orgs = Organisations(
        build_directory(settings), identity, _audit(settings), settings.default_lender_org
    )
    orgs.ensure_organisation(
        Organisation(id=settings.default_lender_org, name="Demo", type=OrgType.LENDER)
    )
    member = orgs.add_to(
        settings.default_lender_org,
        email="o@demo.test",
        display_name="",
        password="password1",
        role=Role.OFFICER,
    )
    client = TestClient(create_app(settings, identity=identity))
    assert client.get(f"/cases/{legacy_id}", headers=as_(member.uid)).status_code == 200
