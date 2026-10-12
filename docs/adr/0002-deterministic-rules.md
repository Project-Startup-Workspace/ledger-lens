# 0002. Compliance pass/fail is decided by code, not by a model

- Status: accepted
- Date: 2026-10-12

## Context
A wrong compliance result creates liability for the lender. Regulators and auditors need to see why a check passed, and the same case must always give the same answer.

## Decision
- Rules are versioned JSON in `rule-packs/`, evaluated by a small deterministic engine over named facts.
- Gemini reads evidence and explains results; it never decides pass or fail.
- Retrieval (RAG Engine) only improves citation excerpts; when it is unavailable, the pack's summary is used.
- Uncertain outcomes (sanctions similarity, missing bias report) produce `review`, which routes the case to a person.

## Consequences
- Adding a country is adding data and tests, not code.
- Rules that need judgement (for example "the loan purpose is productive") are out of scope for automatic checks. They belong in the officer's checklist.
- Rule packs need regular legal review; each pack carries `last_checked` and `review_status`.
