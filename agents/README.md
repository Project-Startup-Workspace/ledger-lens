# ledger_lens (Python)

The five agents, the coordinator, the HTTP API, the ADK workflow and the AuditPulse A2A service.

```
ledger_lens/
├── coordinator.py   # runs the agents in order on a case; every step saved and audited
├── demo.py          # opens the synthetic demo cases
├── api/             # FastAPI app for the officer web app (OpenAPI at /docs)
├── adk_app.py       # the same stages as an ADK Workflow (root_agent) for Agent Runtime
├── a2a_server.py    # AuditPulse alone, as an Agent2Agent service
├── evidence/        # agent 1: read notebooks and statements; cash flow
├── consistency/     # agent 2: notebook vs statement, week by week
├── risk/            # agent 3: score, reason codes, path to approval, model card
├── auditpulse/      # agent 4: rule packs, citations, sanctions, Key Fact Statement
├── explain/         # agent 5: officer report, borrower explanation, speech
├── audit_trail/     # hash-chained events, signed audit packs, verifier CLI
└── shared/          # contracts, config, logging, PII masking, LLM gateway, storage
```

Each agent folder has its own README covering its inputs, outputs, model and limits.

## Run

```bash
make api    # http://localhost:8080/docs
make a2a    # http://localhost:8081/.well-known/agent-card.json
```

Settings come from `LL_*` environment variables or the repo-root `.env` (see `.env.example`). By default everything runs offline: recorded model responses for the demo pages, local files under `.data/`, and a local signing key.

## Test

```bash
make check   # ruff, mypy, pytest
```
