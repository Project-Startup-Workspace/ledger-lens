# Data and consent policy

## 1. Consent before processing
No evidence about an applicant is read until the applicant consents. The case records when consent was given, how (signature, recorded verbal consent, or digital) and which consent text version was shown. Without consent, AuditPulse fails rule `ALL-CON-01` and the case cannot proceed.

## 2. Minimum personal data
Cases hold only what underwriting needs: name, date of birth, national ID, phone, business details and evidence files.

## 3. Masking
Logs and audit events never contain names, national IDs or phone numbers in plain text (`ledger_lens.shared.pii`). Audit events store pseudonyms and hashes.

## 4. Storage and residency
Evidence and case files stay in the deployment's own region. India requires storage in India (rule `IN-DAT-01`), so lending there needs an India-hosted instance.

## 5. Development data
Repositories, tests and demos use synthetic data only, labelled `synthetic` in file names.
