# Ledger Lens

**Ledger Lens turns a shopkeeper's handwritten notebook into a credit file that a lender can trust and a regulator can audit, in any JAPAC language.**

A loan officer photographs the applicant's notebook. Five agents then do the work:

1. **Evidence** reads every line, in any script, with a box showing where each figure came from.
2. **Consistency** checks the notebook against the applicant's wallet statement to catch pages written the night before.
3. **Risk** gives an explainable grade with reason codes and a "path to approval".
4. **AuditPulse** checks the decision against the lending rules of Sri Lanka, Singapore or India, citing each rule.
5. **Explain** writes the officer's report and explains the outcome to the borrower in their own language.

The officer decides. Every step is recorded in a hash-chained audit trail and exported as a signed audit pack.

See [`docs/architecture.md`](docs/architecture.md) for how it fits together and [`docs/roadmap.md`](docs/roadmap.md) for progress.

## Quick start (5 minutes, no cloud account)

Needs [uv](https://docs.astral.sh/uv/) and Node 24.

```bash
make setup            # Python and web dependencies, git hooks
make api              # terminal 1: API on http://localhost:8080 (docs at /docs)
cd web && npm run dev # terminal 2: officer app on http://localhost:3000
```

Open a demo case, press **Assess**, then try the jurisdiction switcher, the decision and **Export audit pack**. Everything runs offline on synthetic data with recorded model responses. To use Gemini, copy `.env.example` to `.env` and set `LL_LLM_PROVIDER`.

Or run everything in containers: `docker compose up --build`.

## Folder map

| Folder | Contents |
|---|---|
| `agents/` | Python: the five agents, coordinator, API, ADK workflow, A2A service, tests |
| `web/` | Next.js officer app |
| `rule-packs/` | Versioned lending rules per country, as data |
| `ml/` | Risk model artifacts, synthetic training data, BigQuery ML SQL |
| `eval/` | Accuracy and fairness results |
| `demo-data/` | Synthetic notebooks, statements, labels and recorded responses |
| `infra/` | Dockerfiles and Google Cloud setup |
| `docs/` | Architecture, decision records, roadmap, demo script, data policy |

## Development

`main` holds released states; work happens on feature branches from `dev`, merged by pull request. Run `make check` before pushing; CI runs the same checks plus image builds and a secret scan.

Status: competition build. The risk model is illustrative (synthetic training data), and rule packs are drafts pending legal review.
