# Rule packs

Per-country lending rules, as versioned data. The AuditPulse engine (`agents/ledger_lens/auditpulse`) runs them against each credit file. Adding a country means adding a folder here, not writing Python.

| Folder | Jurisdiction | Main source |
|---|---|---|
| `common/` | Applied in every market | Consent policy, sanctions screening |
| `lk/` | Sri Lanka | Microfinance and Credit Regulatory Authority Act, No. 9 of 2026 |
| `sg/` | Singapore | MAS Guidelines on AI Risk Management (Oct 2026) |
| `in/` | India | RBI (Digital Lending) Directions, 2025 |

Each rule has a check over named facts (see `schema.json`), a stage (`pre_decision` or `post_decision`), and an `on_fail` of `fail` or `review`. A `review` result sends the case to a person and never rejects it automatically. Every rule cites at least one clause.

Facts available to checks are listed in `agents/ledger_lens/auditpulse/facts.py`.

All packs are **drafts** until reviewed by local counsel (`review_status`).
