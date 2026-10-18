# Ledger Lens

**Ledger Lens helps microbusinesses turn everyday financial records into actionable insights and traceable evidence that owners, auditors and financial institutions can use together.**

Microbusiness records are scattered and hard to use, check or share. Owners struggle to see where they stand, auditors spend days rebuilding evidence, and lenders have no clear basis for a decision. Ledger Lens puts all three on one platform:

- **Business owners** photograph their notebook, see weekly cash-flow insights and their loan readiness, and decide which lender or audit firm sees their records. An accountant can upload records and answer requests for them.
- **Lenders** work the applications sent to them: loan officers prepare, and an assigned credit reviewer decides.
- **Audit firms** audit the cases they are granted: an audit officer requests evidence and records findings, and an audit reviewer approves the report.
- **The platform admin** approves organisations and runs the platform's settings, and never sees a case without time-limited support access.

Sign-in and roles use Firebase Authentication. Under every case, five agents do the work:

1. **Evidence** reads every line, in any script, with a box showing where each figure came from.
2. **Consistency** checks the notebook against the applicant's wallet statement to catch pages written the night before.
3. **Risk** gives an explainable grade with reason codes and a "path to approval".
4. **AuditPulse** checks the decision against the lending rules of Sri Lanka, Singapore or India, citing each rule.
5. **Explain** writes the officer's report and explains the outcome to the borrower in their own language.

A person decides. Every step is recorded in a hash-chained audit trail and exported as a signed audit pack.

**Try it:** https://ledger-lens-512003.web.app. [`docs/testing.md`](docs/testing.md) walks through every role and use case.

See [`docs/architecture.md`](docs/architecture.md) for how it fits together and [`docs/roadmap.md`](docs/roadmap.md) for progress.

## Quick start (5 minutes, no cloud account)

Needs [uv](https://docs.astral.sh/uv/) and Node 24.

```bash
make setup            # Python and web dependencies, git hooks
make api              # terminal 1: API on http://localhost:8080 (docs at /docs)
cd web && npm run dev # terminal 2: web app on http://localhost:3000
```

Open a demo case, press **Assess**, then try the jurisdiction switcher, the decision and **Export audit pack**. Everything runs offline on synthetic data with recorded model responses. To use Gemini, copy `.env.example` to `.env` and set `LL_LLM_PROVIDER`.

Or run everything in containers: `docker compose up --build`.

## Folder map

| Folder | Contents |
|---|---|
| `agents/` | Python: the five agents, coordinator, API, ADK workflow, A2A service, tests |
| `web/` | Next.js web app, with a view for each role |
| `rule-packs/` | Versioned lending rules per country, as data |
| `ml/` | Risk model artifacts, synthetic training data, BigQuery ML SQL |
| `eval/` | Accuracy and fairness results |
| `demo-data/` | Synthetic notebooks, statements, labels and recorded responses |
| `infra/` | Dockerfiles and Google Cloud setup |
| `docs/` | Architecture, decision records, roadmap, testing guide, demo script, data policy |

## Development

`main` holds released states; work happens on feature branches from `dev`, merged by pull request. Run `make check` before pushing. `make emulators && make test-integration` tests the Firestore and Cloud Storage adapters against their emulators in Docker. CI runs all of these, plus image builds and a secret scan.

Status: competition build. The risk model is illustrative (synthetic training data), and rule packs are drafts pending legal review.

## Licence

Copyright (c) 2026 the FireHackers team. All rights reserved. The code is public only for judging in the AI Builder Cup; see [LICENSE](LICENSE) for the evaluation permission and its limits.
