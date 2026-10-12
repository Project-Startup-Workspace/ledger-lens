# 0004. Hash-chained audit events, signed and locked audit packs

- Status: accepted
- Date: 2026-10-12

## Context
A lender must show a regulator what happened on each credit file, and prove the record was not changed afterwards. A plain database table can be edited by anyone with write access, and a hash chain on its own can be rebuilt from scratch by whoever holds the data.

## Decision
- Every case step appends an event that includes the SHA-256 of the previous event (a hash chain).
- Exports are zip "audit packs" with a manifest of file hashes and the chain head. The lender signs the manifest with Ed25519, using a Cloud KMS key in production.
- Packs are verifiable offline by a small CLI against the lender's published public key.
- In the cloud, packs are also written to a Cloud Storage bucket with a locked retention policy (Bucket Lock).

## Consequences
- Any edit, deletion, reordering or rebuild of the record is detectable by anyone holding the pack and the lender's public key.
- The chain proves integrity, not truth: a wrong event recorded at the time stays wrong. Officer overrides therefore record a reason.
- Events must stay small and masked; personal data lives in the case file, not in the chain.
- Key rotation needs the old public keys kept published for as long as their packs are retained.
