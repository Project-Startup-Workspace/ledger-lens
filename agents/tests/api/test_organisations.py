"""Organisations and roles through the API, with Firebase replaced by an in-memory fake.

Each test follows one row of the role table: platform, lender, business or audit firm.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ledger_lens.api.app import create_app
from ledger_lens.audit_trail.stores import build_audit_store
from ledger_lens.organisations import Organisations
from ledger_lens.shared.config import Settings
from ledger_lens.shared.directory import LocalDirectory, build_directory
from ledger_lens.shared.identity import AccountExistsError, InvalidTokenError, SignedIn
from ledger_lens.shared.schemas import Organisation, OrgType, Role, utc_now

DEMO = "synthetic-grocer-kandy"
PASSWORD = "password1"
APPLICATION = {
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


class Api:
    """The test client, signed in as whoever is named."""

    def __init__(self, client: TestClient, people: dict[str, str]) -> None:
        self.client = client
        self.people = people

    def __call__(self, who: str, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"x-ll-id-token": self.people.get(who, who)}
        return self.client.request(method, path, headers=headers, **kwargs)

    def ok(self, who: str, method: str, path: str, **kwargs: Any) -> Any:
        response = self(who, method, path, **kwargs)
        assert response.status_code < 300, f"{who} {method} {path}: {response.text}"
        return response.json()


@pytest.fixture
def identity() -> FakeIdentity:
    return FakeIdentity()


@pytest.fixture
def api(settings: Settings, identity: FakeIdentity) -> Api:
    """A platform admin, two lenders and an audit firm, with one person per role."""
    client = TestClient(create_app(settings, identity=identity))
    orgs = Organisations(
        build_directory(settings),
        identity,
        build_audit_store(settings),
        settings.default_lender_org,
    )
    people: dict[str, str] = {}
    root = orgs.ensure_platform_admin("root@ll.test", "Root", PASSWORD)
    people["root"] = root.uid
    call = Api(client, people)

    def create(name: str, kind: str, admin: str) -> str:
        body = {
            "name": name,
            "type": kind,
            "admin": {"email": f"{admin}@ll.test", "display_name": name, "password": PASSWORD},
        }
        org = call.ok("root", "POST", "/organisations", json=body)
        people[admin] = next(u for u, (e, _) in identity.accounts.items() if e.startswith(admin))
        return str(org["id"])

    people["lender"] = create("Lanka Micro", "lender", "bank_admin")
    people["other_lender"] = create("Other Bank", "lender", "other_admin")
    people["firm"] = create("Clear Audit", "audit_firm", "audit_admin")

    def add(admin: str, name: str, role: str) -> None:
        body = {"email": f"{name}@ll.test", "password": PASSWORD, "role": role}
        people[name] = call.ok(admin, "POST", "/members", json=body)["uid"]

    add("bank_admin", "loan_officer", "loan_officer")
    add("bank_admin", "reviewer", "credit_reviewer")
    add("bank_admin", "reviewer2", "credit_reviewer")
    add("audit_admin", "audit_officer", "audit_officer")
    add("audit_admin", "audit_reviewer", "audit_reviewer")
    return call


def owner_with_application(api: Api, identity: FakeIdentity) -> str:
    """Selvi signs up, registers her business, adds an accountant and opens an application."""
    api.people["owner"] = identity.sign_up("selvi@shop.test", "Selvi")
    assert api.ok("owner", "GET", "/me")["org"] is None
    registered = api.ok("owner", "POST", "/me/organisation", json={"name": "Selvi Stores"})
    assert registered["role"] == "owner" and registered["org"]["status"] == "active"
    assert identity.claims[api.people["owner"]]["org_type"] == "business"
    body = {"email": "books@shop.test", "password": PASSWORD, "role": "accountant"}
    api.people["accountant"] = api.ok("owner", "POST", "/members", json=body)["uid"]
    return str(api.ok("owner", "POST", "/cases", json=APPLICATION)["case_id"])


def upload(api: Api, who: str, case_id: str, content: bytes) -> Any:
    return api(
        who,
        "POST",
        f"/cases/{case_id}/evidence",
        data={"kind": "notebook"},
        files={"file": ("p.png", b"\x89PNG " + content, "image/png")},
    )


def lender_case(api: Api) -> str:
    case_id = api.ok("loan_officer", "POST", f"/demo-cases/{DEMO}")["case_id"]
    api.ok("loan_officer", "POST", f"/cases/{case_id}/assess")
    return str(case_id)


def test_sign_in_is_required(api: Api) -> None:
    assert api.client.get("/cases").status_code == 401
    assert api("forged", "GET", "/cases").status_code == 401


def test_business_owner_and_accountant(api: Api, identity: FakeIdentity) -> None:
    case_id = owner_with_application(api, identity)
    assert upload(api, "accountant", case_id, b"page 1").status_code == 201
    assert api("bank_admin", "GET", f"/cases/{case_id}").status_code == 404  # still private

    # Only the owner authorises sharing.
    send = {"lender_org_id": api.people["lender"]}
    assert api("accountant", "POST", f"/cases/{case_id}/send", json=send).status_code == 403
    firm = {"grantee_org_id": api.people["firm"]}
    assert api("accountant", "POST", "/grants", json=firm).status_code == 403
    assert api.ok("owner", "POST", f"/cases/{case_id}/send", json=send)["lender_org_id"]
    other = {"lender_org_id": api.people["other_lender"]}
    assert api("owner", "POST", f"/cases/{case_id}/send", json=other).status_code == 403

    assert api("bank_admin", "GET", f"/cases/{case_id}").status_code == 200
    assert api("other_admin", "GET", f"/cases/{case_id}").status_code == 404
    assert api.ok("other_admin", "GET", "/cases") == []

    # Sent: the business adds evidence only to answer a request.
    assert upload(api, "accountant", case_id, b"page 2").status_code == 403
    ask = {"addressed_to": "business", "message": "Please add last month's wallet statement."}
    case = api.ok("loan_officer", "POST", f"/cases/{case_id}/requests", json=ask)
    request_id = case["requests"][0]["id"]
    assert upload(api, "accountant", case_id, b"page 2").status_code == 201
    assert api("accountant", "POST", f"/cases/{case_id}/assess").status_code == 403
    answer = {"answer": "Added the statement."}
    path = f"/cases/{case_id}/requests/{request_id}/answer"
    assert api("loan_officer", "POST", path, json=answer).status_code == 403  # not theirs
    answered = api.ok("accountant", "POST", path, json=answer)
    assert answered["requests"][0]["answered_by"] == "books@shop.test"
    assert upload(api, "accountant", case_id, b"page 3").status_code == 403

    decide = {"outcome": "approve", "reason": "mine"}
    assert api("owner", "POST", f"/cases/{case_id}/decision", json=decide).status_code == 403
    events = api.ok("owner", "GET", f"/cases/{case_id}/audit")["events"]
    assert [e["event_type"] for e in events][-3:] == [
        "evidence_requested",
        "evidence_uploaded",
        "evidence_request_answered",
    ]


def test_bank_loan_officer_prepares_and_an_assigned_reviewer_decides(api: Api) -> None:
    case_id = lender_case(api)
    decide = {"outcome": "approve", "reason": "Steady sales"}
    decision = f"/cases/{case_id}/decision"
    assert api("loan_officer", "POST", decision, json=decide).status_code == 403
    assert api("reviewer", "POST", decision, json=decide).status_code == 403  # not assigned
    assert api("reviewer", "POST", f"/demo-cases/{DEMO}").status_code == 403

    reviewers = api.ok("loan_officer", "GET", "/colleagues?role=credit_reviewer")
    assert {r["email"] for r in reviewers} == {"reviewer@ll.test", "reviewer2@ll.test"}
    assign = {"reviewer_uid": api.people["reviewer"]}
    api.ok("loan_officer", "POST", f"/cases/{case_id}/credit-review", json=assign)
    assert api("reviewer2", "POST", decision, json=decide).status_code == 403
    decided = api.ok("reviewer", "POST", decision, json=decide)
    assert decided["decision"]["officer_id"] == "reviewer@ll.test"

    not_reviewer = {"reviewer_uid": api.people["loan_officer"]}
    other_case = lender_case(api)
    path = f"/cases/{other_case}/credit-review"
    assert api("loan_officer", "POST", path, json=not_reviewer).status_code == 422


def test_audit_engagement_from_assignment_to_approved_report(api: Api) -> None:
    case_id = lender_case(api)
    case_path = f"/cases/{case_id}"
    assert api("audit_admin", "GET", case_path).status_code == 404  # no grant yet

    grant = api.ok("bank_admin", "POST", "/grants", json={"grantee_org_id": api.people["firm"]})
    assert grant["status"] == "pending"
    received = api.ok("audit_officer", "GET", "/grants")
    assert received[0]["grantor_name"] == "Lanka Micro"
    assert api("audit_admin", "GET", case_path).status_code == 404  # not yet accepted
    accept = f"/grants/{grant['id']}/accept"
    assert api("audit_officer", "POST", accept).status_code == 403  # the firm's admin answers
    assert api.ok("audit_admin", "POST", accept)["status"] == "active"
    # The admin and reviewers see the granted cases; an audit officer only assigned ones.
    assert [c["case_id"] for c in api.ok("audit_admin", "GET", "/cases")] == [case_id]
    assert api.ok("audit_officer", "GET", "/cases") == []
    assert api("audit_officer", "GET", case_path).status_code == 404

    officers = api.ok("audit_admin", "GET", "/colleagues?role=audit_officer")
    assign = {"assignee_uid": officers[0]["uid"]}
    assert api("audit_reviewer", "POST", f"{case_path}/engagements", json=assign).status_code == 403
    api.ok("audit_admin", "POST", f"{case_path}/engagements", json=assign)
    assert [c["case_id"] for c in api.ok("audit_officer", "GET", "/cases")] == [case_id]

    ask = {"addressed_to": "lender", "message": "Send the signed agreement."}
    asked = api.ok("audit_officer", "POST", f"{case_path}/requests", json=ask)
    path = f"{case_path}/requests/{asked['requests'][0]['id']}/answer"
    api.ok("loan_officer", "POST", path, json={"answer": "Attached to the file."})

    submit = f"{case_path}/findings/submit"
    assert api("audit_officer", "POST", submit).status_code == 409  # no findings yet
    finding = {"severity": "observation", "note": "Notebook totals match the wallet."}
    assert api("audit_reviewer", "POST", f"{case_path}/findings", json=finding).status_code == 403
    api.ok("audit_officer", "POST", f"{case_path}/findings", json=finding)
    case = api.ok("audit_officer", "POST", submit)
    engagement = case["engagements"][0]
    assert engagement["status"] == "submitted"

    review = f"{case_path}/engagements/{engagement['id']}/review"
    approve = {"approve": True, "note": "Agreed."}
    assert api("audit_officer", "POST", review, json=approve).status_code == 403
    returned = api.ok("audit_reviewer", "POST", review, json={"approve": False, "note": "More"})
    assert returned["engagements"][0]["status"] == "returned"
    api.ok("audit_officer", "POST", f"{case_path}/findings", json=finding)
    api.ok("audit_officer", "POST", submit)
    final = api.ok("audit_reviewer", "POST", review, json=approve)["engagements"][0]
    assert final["status"] == "approved" and final["report_snapshot"]
    assert api("audit_reviewer", "POST", f"{case_path}/audit-pack").status_code == 200

    api.ok("bank_admin", "POST", f"/grants/{grant['id']}/revoke")
    assert api("audit_reviewer", "GET", case_path).status_code == 404
    log = api.ok("bank_admin", "GET", "/organisation/audit")
    assert log["verification"]["valid"]
    assert [e["event_type"] for e in log["events"]][-2:] == ["access_granted", "access_revoked"]


def test_an_audit_firm_declines_and_a_request_can_be_withdrawn(api: Api) -> None:
    case_path = f"/cases/{lender_case(api)}"
    firm = {"grantee_org_id": api.people["firm"]}
    first = api.ok("bank_admin", "POST", "/grants", json=firm)
    assert api.ok("bank_admin", "POST", "/grants", json=firm)["id"] == first["id"]  # one open
    assert api("bank_admin", "POST", f"/grants/{first['id']}/accept").status_code == 404

    declined = api.ok("audit_admin", "POST", f"/grants/{first['id']}/decline")
    assert declined["status"] == "declined" and declined["responded_by"]
    assert api("audit_admin", "POST", f"/grants/{first['id']}/accept").status_code == 422
    assert api("audit_admin", "GET", case_path).status_code == 404

    again = api.ok("bank_admin", "POST", "/grants", json=firm)  # asked again after a no
    assert again["id"] != first["id"] and again["status"] == "pending"
    api.ok("bank_admin", "POST", f"/grants/{again['id']}/revoke")
    assert api("audit_admin", "POST", f"/grants/{again['id']}/accept").status_code == 422
    assert api("audit_admin", "GET", case_path).status_code == 404

    events = [
        e["event_type"] for e in api.ok("audit_admin", "GET", "/organisation/audit")["events"]
    ]
    assert events[-4:-2] == ["access_request_received", "access_declined"]
    bank = [e["event_type"] for e in api.ok("bank_admin", "GET", "/organisation/audit")["events"]]
    assert bank[-4:] == [
        "access_requested",
        "access_request_declined",
        "access_requested",
        "access_revoked",
    ]


def test_platform_approves_self_registered_organisations(api: Api, identity: FakeIdentity) -> None:
    api.people["new_bank"] = identity.sign_up("cfo@newbank.test")
    body = {"name": "New Bank", "type": "lender", "jurisdiction": "sg"}
    me = api.ok("new_bank", "POST", "/me/organisation", json=body)
    assert me["role"] == "admin" and me["org"]["status"] == "pending"
    org_id = me["org"]["id"]
    assert api("new_bank", "POST", f"/demo-cases/{DEMO}").status_code == 403
    lenders = api.ok("loan_officer", "GET", "/organisations?type=lender")
    assert "New Bank" not in {o["name"] for o in lenders}  # not offered to owners yet

    status = f"/organisations/{org_id}/status"
    assert api("bank_admin", "POST", status, json={"status": "active"}).status_code == 403
    api.ok("root", "POST", status, json={"status": "active"})
    assert api("new_bank", "POST", f"/demo-cases/{DEMO}").status_code == 201
    api.ok("root", "POST", status, json={"status": "suspended"})
    assert api("new_bank", "GET", "/cases").status_code == 403
    events = [e["event_type"] for e in api.ok("root", "GET", "/organisation/audit")["events"]]
    assert "member_added" in events  # the platform's own chain

    admin = {"email": "second@newbank.test", "password": PASSWORD}
    assert (
        api("bank_admin", "POST", f"/organisations/{org_id}/admins", json=admin).status_code == 403
    )
    added = api.ok("root", "POST", f"/organisations/{org_id}/admins", json=admin)
    assert added["role"] == "admin" and added["org_id"] == org_id

    closed = {"self_registration": False}
    api.ok("root", "POST", "/platform/settings", json=closed)
    api.people["late"] = identity.sign_up("late@firm.test")
    firm = {"name": "Late Audit", "type": "audit_firm"}
    assert api("late", "POST", "/me/organisation", json=firm).status_code == 403


def test_support_access_lets_the_platform_read_for_a_day(api: Api, settings: Settings) -> None:
    case_id = lender_case(api)
    assert api("root", "GET", f"/cases/{case_id}").status_code == 404
    assert api("root", "GET", "/cases").json() == []
    support = {"grantee_org_id": "org_platform"}
    grant = api.ok("bank_admin", "POST", "/grants", json=support)
    assert grant["expires_at"] is not None
    assert api("root", "GET", f"/cases/{case_id}").status_code == 200
    assert api("root", "POST", f"/cases/{case_id}/assess").status_code == 403

    directory = LocalDirectory(settings.data_dir / "directory")
    stored = directory.get_grant(grant["id"])
    assert stored is not None
    directory.save_grant(stored.model_copy(update={"expires_at": utc_now() - timedelta(1)}))
    assert api("root", "GET", f"/cases/{case_id}").status_code == 404


def test_platform_settings_change_the_daily_cap_live(api: Api) -> None:
    assert api("bank_admin", "GET", "/platform/settings").status_code == 403
    before = api.ok("root", "GET", "/platform/settings")
    assert before["effective_daily_model_calls"] == before["deployment_daily_model_calls"]
    after = api.ok("root", "POST", "/platform/settings", json={"daily_model_calls": 450})
    assert after["effective_daily_model_calls"] == 450
    assert after["config"]["updated_by"] == "root@ll.test"


def test_roles_are_checked_against_the_organisation(api: Api) -> None:
    wrong_role = {"email": "x@ll.test", "password": PASSWORD, "role": "audit_officer"}
    assert api("bank_admin", "POST", "/members", json=wrong_role).status_code == 422
    duplicate = {"email": "loan_officer@ll.test", "password": PASSWORD, "role": "loan_officer"}
    assert api("bank_admin", "POST", "/members", json=duplicate).status_code == 409
    assert api("loan_officer", "GET", "/members").status_code == 403
    assert api("root", "POST", f"/demo-cases/{DEMO}").status_code == 403
    body = {"name": "Shop", "type": "business", "admin": duplicate}
    assert api("bank_admin", "POST", "/organisations", json=body).status_code == 403

    officer = api.people["loan_officer"]
    promoted = api.ok("bank_admin", "POST", f"/members/{officer}/role", json={"role": "admin"})
    assert promoted["role"] == "admin"
    removed = api.ok("bank_admin", "POST", f"/members/{officer}/remove")
    assert removed["disabled"] is True
    assert api("loan_officer", "GET", "/cases").status_code == 401
    admin = api.people["bank_admin"]
    assert api("bank_admin", "POST", f"/members/{admin}/remove").status_code == 422


def test_a_member_cannot_register_a_second_organisation(api: Api) -> None:
    again = api("audit_officer", "POST", "/me/organisation", json={"name": "Side shop"})
    assert again.status_code == 422


def test_cases_from_before_organisations_belong_to_the_default_lender(
    settings: Settings, identity: FakeIdentity
) -> None:
    legacy_id = TestClient(create_app(settings)).post(f"/demo-cases/{DEMO}").json()["case_id"]
    orgs = Organisations(
        build_directory(settings),
        identity,
        build_audit_store(settings),
        settings.default_lender_org,
    )
    orgs.ensure_organisation(
        Organisation(id=settings.default_lender_org, name="Demo", type=OrgType.LENDER)
    )
    member = orgs.add_to(
        settings.default_lender_org,
        email="o@demo.test",
        display_name="",
        password=PASSWORD,
        role=Role.LOAN_OFFICER,
    )
    client = TestClient(create_app(settings, identity=identity))
    response = client.get(f"/cases/{legacy_id}", headers={"x-ll-id-token": member.uid})
    assert response.status_code == 200
