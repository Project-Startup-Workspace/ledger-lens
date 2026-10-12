"""The ADK workflow and the AuditPulse A2A service, run in process."""

import asyncio
import json

import pytest

pytest.importorskip("google.adk")

from google.adk.runners import InMemoryRunner
from google.genai import types
from starlette.testclient import TestClient

from ledger_lens.a2a_server import build_app, handle
from ledger_lens.adk_app import build_workflow
from ledger_lens.coordinator import Coordinator, build_services
from ledger_lens.demo import open_demo_case
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import CaseStatus


def test_workflow_runs_every_stage(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case_id = open_demo_case(coordinator, "synthetic-grocer-kandy", "o").case_id

    async def run() -> list[str]:
        runner = InMemoryRunner(agent=build_workflow(coordinator), app_name="ledger_lens")
        session = await runner.session_service.create_session(
            app_name="ledger_lens", user_id="o", state={"case_id": case_id}
        )
        message = types.Content(role="user", parts=[types.Part(text="assess")])
        return [
            part.text
            async for event in runner.run_async(
                user_id="o", session_id=session.id, new_message=message
            )
            if event.content
            for part in event.content.parts or []
            if part.text
        ]

    texts = asyncio.run(run())
    assert texts[-1] == "Assessment complete."
    assert any(t.startswith("Risk grade A") for t in texts)
    assert coordinator.get(case_id).status is CaseStatus.ASSESSED


def test_a2a_handle_checks_a_credit_file(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "o")
    request = json.dumps({"credit_file": case.model_dump(mode="json"), "jurisdiction": "sg"})
    app_auditpulse = build_services(settings).auditpulse
    report = json.loads(handle(app_auditpulse, request))
    assert report["jurisdiction"] == "sg" and report["findings"]
    assert "error" in json.loads(handle(app_auditpulse, "not json"))
    assert "error" in json.loads(handle(app_auditpulse, "[1, 2]"))
    for bad in (5, "sgp"):
        body = json.dumps({"credit_file": case.model_dump(mode="json"), "jurisdiction": bad})
        assert "error" in json.loads(handle(app_auditpulse, body))


def test_a2a_service_publishes_its_agent_card(settings: Settings) -> None:
    settings.a2a_public_url = "https://auditpulse.example.com"
    with TestClient(build_app(settings)) as client:
        card = client.get("/.well-known/agent-card.json").json()
    assert card["name"] == "auditpulse"
    assert card["supportedInterfaces"][0]["url"].startswith("https://auditpulse.example.com")
