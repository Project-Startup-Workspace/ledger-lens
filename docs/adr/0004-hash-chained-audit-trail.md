# 0004. Hash-chained audit events and locked audit packs

- Status: accepted
- Date: 2026-10-12

## Context
A lender must show a regulator what happened on each credit file, and prove the record was not changed afterwards. A plain database table can be edited by anyone with write access.

## Decision
- Every case step appends an event that includes the SHA-256 of the previous event (a hash chain).
- Exports are zip "audit packs" with a manifest of file hashes and the chain head, verifiable offline by a small CLI.
- In the cloud, packs are written to a Cloud Storage bucket with a locked retention policy (Bucket Lock).

## Consequences
- Any edit, deletion or reordering of past events is detectable by anyone holding the pack.
- The chain proves integrity, not truth: a wrong event recorded at the time stays wrong. Officer overrides therefore record a reason.
- Events must stay small and masked; personal data lives in the case file, not in the chain.
