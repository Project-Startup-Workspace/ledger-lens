"""AuditPulse as a standalone Agent2Agent (A2A) service.

Other lenders' systems send a credit file (optionally with a jurisdiction) and receive
the compliance report, without using the rest of Ledger Lens. Stateless: nothing sent
here is stored. Run: `uvicorn ledger_lens.a2a_server:app --port 8081`.

Message text: {"credit_file": {...CreditFile...}, "jurisdiction": "sg"}; a bare
CreditFile is also accepted. The reply is the ComplianceReport as JSON, or
{"error": "..."} when the request cannot be read.
"""

import json
from functools import lru_cache
from urllib.parse import urlparse

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.workflow import START, FunctionNode, Workflow
from google.genai import types
from pydantic import ValidationError
from starlette.applications import Starlette

from ledger_lens.auditpulse.agent import AuditPulse, InvalidJurisdictionError
from ledger_lens.auditpulse.packs import RulePackRegistry
from ledger_lens.auditpulse.retrieval import build_retriever
from ledger_lens.auditpulse.screening import SanctionsScreen
from ledger_lens.shared.config import Settings, get_settings
from ledger_lens.shared.schemas import CreditFile

MAX_REQUEST_CHARS = 2_000_000


def handle(auditpulse: AuditPulse, request_text: str) -> str:
    """Parse one request and return the reply text."""
    if len(request_text) > MAX_REQUEST_CHARS:
        return json.dumps({"error": "request too large"})
    try:
        body = json.loads(request_text)
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object")
        jurisdiction = body.get("jurisdiction") if "credit_file" in body else None
        if jurisdiction is not None and not isinstance(jurisdiction, str):
            raise ValueError("jurisdiction must be a two-letter code")
        case = CreditFile.model_validate(body.get("credit_file", body))
    except (ValueError, ValidationError) as exc:
        return json.dumps({"error": f"could not read the request: {exc}"[:2000]})
    try:
        return auditpulse.check(case, jurisdiction).model_dump_json()
    except InvalidJurisdictionError as exc:
        return json.dumps({"error": str(exc)})


def build_app(settings: Settings) -> Starlette:
    auditpulse = AuditPulse(
        RulePackRegistry(settings.rule_packs_dir),
        build_retriever(settings),
        SanctionsScreen(settings.sanctions_list_path),
        settings,
    )

    def check(node_input: str) -> types.Content:
        return types.Content(role="model", parts=[types.Part(text=handle(auditpulse, node_input))])

    workflow = Workflow(
        name="auditpulse",
        description=(
            "Checks a credit decision against the lending rules of Sri Lanka, Singapore or "
            "India. Send a Ledger Lens CreditFile as JSON; receive a cited compliance report."
        ),
        edges=[(START, FunctionNode(func=check, name="check_compliance"))],
    )
    public = urlparse(settings.a2a_public_url)
    return to_a2a(
        workflow,
        host=public.hostname or "localhost",
        port=public.port or (443 if public.scheme == "https" else 80),
        protocol=public.scheme or "http",
    )


@lru_cache
def _default_app() -> Starlette:
    return build_app(get_settings())


def __getattr__(name: str) -> Starlette:
    if name == "app":
        return _default_app()
    raise AttributeError(name)
