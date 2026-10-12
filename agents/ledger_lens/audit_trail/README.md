# Audit trail

A tamper-evident record of everything that happened on a case.

- **Events** (`chain.py`). Each step (case created, evidence read, risk assessed, decision recorded, and so on) appends an `AuditEvent` holding the hash of the previous event. Payloads are small, masked summaries; the full case is referenced by `snapshot_hash`.
- **Verification.** `verify_chain` recomputes every hash and link and reports the first edit, deletion or reordering.
- **Audit pack** (`pack.py`). A zip with the credit file, events, compliance reports, model card and a manifest of SHA-256 hashes. Verify one offline with:

  ```bash
  cd agents && uv run python -m ledger_lens.audit_trail verify path/to/pack.zip
  ```

- **Storage.** Locally, events are append-only JSON Lines under `LL_DATA_DIR/audit/`. In the cloud, packs are written to a Cloud Storage bucket with a retention policy and Bucket Lock (`LL_AUDIT_BUCKET`), so even administrators cannot delete or replace them before retention ends.

See `docs/adr/0004-hash-chained-audit-trail.md`.
