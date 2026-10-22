# Architecture

Ledger Lens is one platform for the three parties to a microbusiness's finances: the business, its lender and its auditor. Five agents and one human decision sit underneath: Gemini reads, reasons and explains; deterministic code calculates and decides pass/fail; a credit reviewer makes every credit decision.

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
| Explanation agent | `agents/ledger_lens/explain` | Officer report; borrower explanation in their language with an English version for the officer, kept per language; speech | Gemini Pro, Gemini TTS |
| Audit trail | `agents/ledger_lens/audit_trail` | Hash-chained events; signed, verifiable audit packs | none |
| Coordinator | `agents/ledger_lens/coordinator.py` | Runs the stages, enforces case rules, saves and audits every step | — |
| API | `agents/ledger_lens/api` | HTTP for the web app (OpenAPI at `/docs`) | — |
| ADK workflow | `agents/ledger_lens/adk_app.py` | The same stages as an ADK `Workflow` for Agent Runtime | — |
| AuditPulse A2A | `agents/ledger_lens/a2a_server.py` | AuditPulse alone, as an Agent2Agent service for other lenders | — |
| Organisations | `agents/ledger_lens/organisations.py`, `access.py` | Organisations, members, roles, access grants, platform settings; every case permission in one place | — |
| Web app | `web/` | Mobile-first app with a view per role; Firebase sign-in; server-side proxy holds the API token | — |

## Organisations and roles

People sign in with Firebase Authentication. The web app checks the ID token on every request and the API checks it again, then applies the person's role from the directory in Firestore (a copy rides in the token's custom claims for the UI).

| Organisation | Role | May |
|---|---|---|
| Platform | Platform admin | Approve, suspend and add organisations; change platform settings (daily Gemini cap, self-registration); read a case only under a 24-hour support grant |
| Lender | Admin | Manage staff and roles; ask audit firms to audit, grant support access; every lender task |
| Lender | Loan officer | Open and prepare applications, ask the business for evidence, send a case to a credit reviewer |
| Lender | Credit reviewer | Decide the applications assigned to them |
| Audit firm | Admin | Manage staff; accept or decline requests to audit; assign engagements on accepted organisations' cases |
| Audit firm | Audit officer | Work assigned engagements: request evidence, record findings, submit for review |
| Audit firm | Audit reviewer | Approve findings as the final report, or return them |
| Business | Owner | The business profile; prepare and send applications; acknowledge loan terms; grant access |
| Business | Accountant | Upload records and answer requests; never shares |

Cases carry the lender and the business they belong to. An owner's application is private until the owner sends it to one lender. A lender or business asks an audit firm to audit it; the firm's admin accepts or declines, and the firm sees that organisation's cases only after accepting and while the grant stands. Organisation changes are kept in each organisation's own hash chain, beside the case chains.

## Data flow and contracts

Agents exchange only the Pydantic contracts in `agents/ledger_lens/shared/schemas.py`. No agent imports another's internals. The `CreditFile` accumulates each agent's output and carries a `revision`, so concurrent writers are rejected rather than overwritten.

## Trust and safety

- **Numbers:** extracted amounts carry a box and a confidence; low-confidence lines are excluded from totals and queued for review.
- **Fraud:** the consistency check compares the notebook with a statement the applicant cannot easily fake.
- **Prompt injection:** text read from documents is screened (heuristics, plus Model Armor in the cloud); flagged text is removed. Explanation prompts receive only checked facts, and model output is rejected if it introduces numbers not in those facts.
- **Personal data:** masked in logs and audit events; consent is required before evidence upload.
- **Accountability:** an assigned credit reviewer decides, with a reason, apart from the loan officer who prepared the case; audit findings are approved by someone other than their author; overrides are derived and recorded; identity comes from a verified sign-in token, never from the request body.
- **Least privilege:** each role sees and changes only what the table above allows; a case someone may not see is reported as missing. The platform admin sees no case unless an organisation grants time-limited support access.
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
| Serving | `next dev` and `uvicorn` | Firebase Hosting → Cloud Run (web, API, A2A) |
| Sign-in | single lender, no sign-in (or the Firebase Auth emulator) | Firebase Authentication; directory in Firestore |

Decisions behind this design are in `docs/adr/`.
