# Architecture

Ledger Lens is five agents and one human decision. Gemini reads, reasons and explains; deterministic code calculates and decides pass/fail. The officer makes every credit decision.

```
 phone camera / CSV                                                       officer
        │                                                                    │
        ▼                                                                    ▼
 ┌─────────────┐  entries   ┌──────────────┐  flags   ┌──────────┐  grade  ┌────────────┐  report  ┌───────────┐
 │ 1 Evidence  │──────────▶│ 2 Consistency │────────▶│ 3 Risk    │───────▶│ 4 AuditPulse│────────▶│ 5 Explain │──▶ decision
 │ Gemini read │ cash flow  │ notebook vs   │         │ logistic  │ reasons │ rule packs  │ findings│ officer + │    (human)
 │ + Python Σ  │            │ wallet, weekly│         │ + Shapley │ path    │ + citations │         │ borrower  │
 └─────────────┘            └──────────────┘         └──────────┘         └────────────┘         └───────────┘
        │                         │                       │                     │                      │
        └─────────────────────────┴──── every step ───────┴─────────────────────┴──────────────────────┘
                                         ▼
                          hash-chained audit events ──▶ signed audit pack (Ed25519)
```

## Components

| Component | Code | What it owns | Model |
|---|---|---|---|
| Evidence agent | `agents/ledger_lens/evidence` | Read pages into ledger entries with boxes and confidence; weekly cash flow in Python | Gemini Flash, structured output |
| Consistency agent | `agents/ledger_lens/consistency` | Weekly notebook vs statement comparison; flags with officer questions | none |
| Risk agent | `agents/ledger_lens/risk` | Probability of default, grade, reason codes, path to approval, model card | logistic regression (BigQuery ML or local) |
| AuditPulse | `agents/ledger_lens/auditpulse` | Per-country rule packs, citations, sanctions screening, Key Fact Statement | none for pass/fail; RAG Engine for excerpts |
| Explanation agent | `agents/ledger_lens/explain` | Officer report; borrower explanation in their language; speech | Gemini Pro, Gemini TTS |
| Audit trail | `agents/ledger_lens/audit_trail` | Hash-chained events; signed, verifiable audit packs | none |
| Coordinator | `agents/ledger_lens/coordinator.py` | Runs the stages, enforces case rules, saves and audits every step | — |
| API | `agents/ledger_lens/api` | HTTP for the web app (OpenAPI at `/docs`) | — |
| ADK workflow | `agents/ledger_lens/adk_app.py` | The same stages as an ADK `Workflow` for Agent Runtime | — |
| AuditPulse A2A | `agents/ledger_lens/a2a_server.py` | AuditPulse alone, as an Agent2Agent service for other lenders | — |
| Web app | `web/` | Mobile-first officer app; server-side proxy holds the API token | — |

## Data flow and contracts

Agents exchange only the Pydantic contracts in `agents/ledger_lens/shared/schemas.py`. No agent imports another's internals. The `CreditFile` accumulates each agent's output and carries a `revision`, so concurrent writers are rejected rather than overwritten.

## Trust and safety

- **Numbers:** extracted amounts carry a box and a confidence; low-confidence lines are excluded from totals and queued for review.
- **Fraud:** the consistency check compares the notebook with a statement the applicant cannot easily fake.
- **Prompt injection:** text read from documents is screened (heuristics, plus Model Armor in the cloud); flagged text is removed. Explanation prompts receive only checked facts, and model output is rejected if it introduces numbers not in those facts.
- **Personal data:** masked in logs and audit events; consent is required before evidence upload.
- **Accountability:** officers decide, with a reason; overrides are derived and recorded; identity comes from sign-in, never from the request body.
- **Audit:** every step appends to a hash chain; exports are signed with the lender's key and verifiable offline.

## Environments

| | Local (default) | Google Cloud |
|---|---|---|
| Gemini | recorded responses (`demo-data/fixtures`) | Vertex AI (`LL_LLM_PROVIDER=vertex`) |
| Case files, audit events | JSON files in `.data/` | Firestore |
| Evidence, audit packs | `.data/` folders | Cloud Storage (packs with Bucket Lock) |
| Signing key | generated PEM in `.data/keys` | Cloud KMS Ed25519 |
| Safety screen | heuristics | Model Armor + heuristics |
| Citations | rule-pack summaries | RAG Engine passages |

Decisions behind this design are in `docs/adr/`.
