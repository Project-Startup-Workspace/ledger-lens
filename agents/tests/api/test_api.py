"""HTTP API behaviour through FastAPI's test client."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from ledger_lens.api.app import create_app
from ledger_lens.shared.config import Settings
from tests.conftest import DEMO


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_full_officer_flow(client: TestClient) -> None:
    case = client.post("/demo-cases/synthetic-grocer-kandy").json()
    case_id = case["case_id"]
    assert len(case["evidence"]) == 5

    assessed = client.post(f"/cases/{case_id}/assess").json()
    assert assessed["status"] == "assessed" and assessed["risk"]["grade"] == "A"

    page = assessed["evidence"][0]
    image = client.get(f"/cases/{case_id}/evidence/{page['id']}/file")
    assert image.headers["content-type"] == "image/png" and image.content.startswith(b"\x89PNG")

    india = client.get(f"/cases/{case_id}/compliance", params={"jurisdiction": "in"}).json()
    assert india["jurisdiction_name"] == "India"

    explanation = client.post(f"/cases/{case_id}/explanation", json={"language": "en"}).json()
    assert explanation["written_by"] == "template"
    assert client.get(f"/cases/{case_id}/report").text.startswith("# Credit file")

    client.post(f"/cases/{case_id}/disclosure/acknowledge", json={"blank_fields": []})
    decided = client.post(
        f"/cases/{case_id}/decision",
        json={"outcome": "approve", "reason": "Steady sales"},
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:priya@lender.example"},
    ).json()
    assert decided["decision"]["overridden"] is False
    assert decided["decision"]["officer_id"] == "priya@lender.example"

    assert client.get(f"/cases/{case_id}/audit").json()["verification"]["valid"]
    pack = client.get(f"/cases/{case_id}/audit-pack")
    assert pack.headers["content-type"] == "application/zip"
    check = client.post("/audit-packs/verify", files={"file": ("p.zip", pack.content)}).json()
    assert check["valid"] and check["key_trusted"]

    listed = client.get("/cases").json()
    assert listed[0]["case_id"] == case_id and listed[0]["grade"] == "A"


def test_errors_map_to_http_statuses(client: TestClient) -> None:
    assert client.get("/cases/case_missing").status_code == 404
    case_id = client.post("/demo-cases/synthetic-grocer-kandy").json()["case_id"]
    decide = {"outcome": "approve", "reason": "x"}
    assert client.post(f"/cases/{case_id}/decision", json=decide).status_code == 409
    assert client.post("/demo-cases/nope").status_code == 404
    client.post(f"/cases/{case_id}/assess")
    bad_language = client.post(f"/cases/{case_id}/explanation", json={"language": "xx"})
    assert bad_language.status_code == 422
    assert client.get(f"/cases/{case_id}/explanation/audio").status_code == 503
    bad_code = client.get(f"/cases/{case_id}/compliance", params={"jurisdiction": "sgp"})
    assert bad_code.status_code == 422
    assert client.post(f"/cases/{case_id}/decision", json=decide).status_code == 200
    assert client.post(f"/cases/{case_id}/decision", json=decide).status_code == 409
    assert client.post(f"/cases/{case_id}/assess").status_code == 409


def test_uploads_are_type_and_size_checked(client: TestClient) -> None:
    case_id = client.post("/demo-cases/synthetic-grocer-kandy").json()["case_id"]
    url = f"/cases/{case_id}/evidence"
    exe = client.post(
        url, data={"kind": "notebook"}, files={"file": ("a.exe", b"MZ", "application/x-msdownload")}
    )
    assert exe.status_code == 415
    empty = client.post(url, data={"kind": "notebook"}, files={"file": ("a.png", b"", "image/png")})
    assert empty.status_code == 422
    page = (DEMO / "synthetic-grocer-kandy" / "notebook-p1.png").read_bytes()
    ok = client.post(url, data={"kind": "notebook"}, files={"file": ("p.png", page, "image/png")})
    assert ok.status_code == 201 and ok.json()["kind"] == "notebook"


def test_officer_header_is_trusted_only_with_a_token(settings: Settings) -> None:
    open_client = TestClient(create_app(settings))
    case = open_client.post("/demo-cases/synthetic-grocer-kandy", headers={"X-Officer-Id": "spoof"})
    events = open_client.get(f"/cases/{case.json()['case_id']}/audit").json()["events"]
    assert events[0]["actor"] == "officer"  # no token, so the header is ignored

    settings.api_token = SecretStr("s3cret")
    proxied = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer s3cret", "X-Officer-Id": "officer-7"}
    case = proxied.post("/demo-cases/synthetic-grocer-kandy", headers=headers)
    events = proxied.get(f"/cases/{case.json()['case_id']}/audit", headers=headers).json()
    assert events["events"][0]["actor"] == "officer-7"


def test_bearer_token_is_enforced_when_configured(settings: Settings) -> None:
    settings.api_token = SecretStr("s3cret")
    client = TestClient(create_app(settings))
    assert client.get("/health").status_code == 200  # health stays open for probes
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/cases", headers={"Authorization": "Bearer s3cret"}).status_code == 200
