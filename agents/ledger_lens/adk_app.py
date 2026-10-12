"""The five agents as an ADK workflow, for deployment on Agent Runtime.

Each node runs one coordinator stage on the case named by `case_id` in session state,
so the managed runtime gets per-stage tracing while sharing the API's exact logic.
"""

from collections.abc import Callable
from functools import lru_cache
from itertools import pairwise

from google.adk.workflow import START, FunctionNode, Workflow
from google.genai import types

from ledger_lens.coordinator import Coordinator, build_services
from ledger_lens.shared.config import get_settings
from ledger_lens.shared.schemas import CreditFile

Stage = Callable[[CreditFile], None]
Summary = Callable[[CreditFile], str]


def _node(coordinator: Coordinator, name: str, stage: Stage, summary: Summary) -> FunctionNode:
    def run(case_id: str) -> types.Content:
        case = coordinator.run_stage(case_id, stage)
        return types.Content(role="model", parts=[types.Part(text=summary(case))])

    run.__name__ = name
    return FunctionNode(func=run, name=name)


def build_workflow(coordinator: Coordinator) -> Workflow:
    c = coordinator
    nodes = [
        _node(c, "evidence", c.read_evidence, lambda f: f"Read {len(f.extractions)} documents."),
        _node(
            c,
            "consistency",
            c.check_consistency,
            lambda f: f"Consistency: {f.consistency.status if f.consistency else 'not run'}.",
        ),
        _node(
            c,
            "risk",
            c.score_risk,
            lambda f: (
                f"Risk grade {f.risk.grade}, recommend {f.risk.recommendation}."
                if f.risk
                else "Risk not scored."
            ),
        ),
        _node(
            c,
            "auditpulse",
            c.check_compliance,
            lambda f: (
                f"Compliance checked under {f.compliance.jurisdiction_name}."
                if f.compliance
                else "Compliance not checked."
            ),
        ),
        _node(c, "explain", c.finish_assessment, lambda f: "Assessment complete."),
    ]
    edges = [(START, nodes[0]), *pairwise(nodes)]
    return Workflow(
        name="ledger_lens",
        description="Turns a notebook and statements into an assessed, audited credit file.",
        edges=edges,
    )


@lru_cache
def _root_agent() -> Workflow:
    return build_workflow(Coordinator(build_services(get_settings())))


def __getattr__(name: str) -> Workflow:
    """ADK loads `root_agent`; built once, lazily, so importing this module stays cheap."""
    if name == "root_agent":
        return _root_agent()
    raise AttributeError(name)
