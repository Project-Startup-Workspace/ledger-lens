# Audit trail

A tamper-evident, signed record of everything that happened on a case.

- **Events** (`chain.py`). Each case step appends an `AuditEvent` holding the hash of the previous event. Payloads are small, masked summaries; the full case is referenced by `snapshot_hash`. The local store locks the file across processes, fsyncs each event, and quarantines a torn tail left by a crash.
- **Verification.** `verify_chain` recomputes every hash and link and reports the first edit, deletion or reordering.
- **Audit pack** (`pack.py`). A zip with the credit file, events, compliance reports, model card, a manifest of SHA-256 hashes, and the lender's **Ed25519 signature** over the manifest (`signing.py`). The signature is what stops someone rebuilding a fresh chain and manifest.
- **Keys.** Locally, a key is generated under `LL_DATA_DIR/keys/`. In the cloud, a Cloud KMS `EC_SIGN_ED25519` key (`LL_AUDIT_KMS_KEY`) signs, and the private key never leaves KMS. The lender publishes the public key so regulators can check origin.
- **Verify offline:**

  ```bash
  cd agents && uv run python -m ledger_lens.audit_trail verify pack.zip --public-key lender.pub.pem
  ```

  Without `--public-key`, the pack is checked against the key it carries: this proves integrity but not origin.

- **Storage.** The coordinator appends events at each step and stores every exported pack. In the cloud, packs go to a Cloud Storage bucket with a locked retention policy (`LL_AUDIT_BUCKET`).

See `docs/adr/0004-hash-chained-audit-trail.md`.
