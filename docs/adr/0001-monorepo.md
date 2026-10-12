# 0001. One monorepo for agents, web, rule packs and docs

- Status: accepted
- Date: 2026-10-12

## Context
A small team has six days to ship five agents, a web app, rule packs and an evaluation suite. Changes regularly cut across these parts, for example a schema change that touches an agent and the UI.

## Decision
Keep everything in one repository with one CI pipeline. Agents share contracts through `agents/ledger_lens/shared/`; rule packs live as data in `rule-packs/`.

## Consequences
- One pull request can change a contract and every consumer at once.
- CI runs all checks on every change; jobs must stay fast.
- Splitting AuditPulse into its own repo later is possible because it only depends on `shared/`.
