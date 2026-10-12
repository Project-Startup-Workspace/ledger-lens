# AuditPulse (agent 4)

Checks a credit file against the lending rules of a jurisdiction. Every finding cites the clause it relies on.

| | |
|---|---|
| Input | `CreditFile`, optional jurisdiction override |
| Output | `ComplianceReport`: one `Finding` per rule (pass, fail, review, pending) with citations |
| Rules | `rule-packs/<jurisdiction>/pack.json` plus `rule-packs/common/pack.json` |
| Model | None for pass/fail. Vertex AI RAG Engine (optional) supplies the regulator's own wording for citations |

- **Deterministic.** Checks are data (`rules.py` evaluates them), so results are testable and reproducible. See ADR 0002.
- **Never auto-rejects on judgement.** `review` findings and sanctions matches go to a person.
- **Stages.** `post_decision` rules (sign-off, signed agreement, Key Fact Statement acknowledgement) stay `pending` until the officer decides.
- **Facts.** The full list a pack may use is in `facts.py`.
- **Disclosure.** `disclosure.key_fact_statement` builds the Key Fact Statement shown before signing.
- **A2A.** The API exposes AuditPulse as an Agent2Agent service, so other lenders' systems can call it on its own.

Known limits: rule packs are drafts until reviewed by local counsel. The sanctions list in this repo is a synthetic sample.
