# Roadmap and tracker

The single source of truth for what is planned, done and left. Tick an item in the same PR that finishes it, and link the PR. Scope changes go here first, so the plan never drifts silently.

Source plans: the Engineering Playbook (issues 1–26) and the Product Blueprint (build plan to the 18 October 2026 submission).

**Legend:** `[x]` done · `[~]` partly done (see note) · `[ ]` not started. Priority P0 means the demo breaks without it, P1 makes it stronger, P2 is cut first.

## Phase 1: build everything locally (offline, no cloud accounts)

| Status | # | Item | Priority | Delivered in |
|---|---|---|---|---|
| [x] | 1a | Repository, `main`/`dev` branches, CI, templates, CODEOWNERS | P0 | #1 |
| [~] | 1b | Branch protection on `main` and `dev` | P0 | Needs a paid GitHub plan or a public repo. PRs are used by convention meanwhile |
| [x] | 2 | Demo notebooks in 3 scripts and wallet statements with a planted mismatch (synthetic) | P0 | #3, #5 |
| [x] | 3 | Shared Pydantic contracts: evidence, cash flow, risk, findings, credit file | P0 | #2 |
| [x] | 4 | Walking skeleton: coordinator + 5 agents end to end | P0 | #9 |
| [x] | 5 | Evidence agent: extraction schema, prompt, bounding boxes | P0 | #3 |
| [x] | 6 | Cash-flow calculator in Python, with unit tests | P0 | #3 |
| [x] | 7 | Evaluation harness: read accuracy per script on the labelled set | P0 | #12 |
| [x] | 8 | Web: camera upload and evidence viewer with highlight boxes | P0 | #10 |
| [x] | 9 | Risk model with Shapley reason codes (local; BigQuery ML SQL ready) | P0 | #5 |
| [x] | 10 | Consistency checker: notebook vs wallet, week by week | P0 | #4 |
| [x] | 11 | Rule-pack JSON schema; Sri Lanka and Singapore packs | P0 | #6 |
| [x] | 12 | Path-to-approval counterfactual | P1 | #5 |
| [~] | 13 | Regulation retrieval; every finding cites a clause | P0 | #6: citations from pack summaries; RAG Engine adapter ready, needs the corpus |
| [x] | 14 | Hash-chained audit trail and signed audit pack export | P0 | #7 |
| [x] | 15 | Jurisdiction switcher and compliance checklist in the UI | P0 | #10 |
| [x] | 16 | India rule pack | P2 | #6 |
| [x] | 17 | AuditPulse exposed as an A2A agent | P2 | #9 |
| [x] | 18 | Explanation agent: officer report, borrower explanation | P0 | #8 |
| [~] | 19 | Spoken explanation with Gemini TTS | P1 | #8: code ready; needs Gemini credentials. Device voice used offline |
| [ ] | 20 | Live voice interview | P2 | Cut until after submission (playbook cut line) |
| [~] | 21 | Full flow on every demo case | P0 | Works locally on all 3 cases; deployed URL pending |
| [~] | 22 | Final evaluation and bias check; results table | P0 | #12: bias check passes (0.97); accuracy on hand-written pages needs Gemini |
| [x] | — | Containers, docker-compose, infra scripts, deploy and eval workflows | P0 | #12, #13 |
| [x] | 25 | README, architecture doc, demo script | P1 | #14 |

## Phase 2: Google Cloud (needs accounts and credentials)

| Status | Item | Needs |
|---|---|---|
| [ ] | GCP project `ledger-lens-dev`, billing with budget alert, APIs enabled | Billing account |
| [ ] | Keyless GitHub → GCP deploys (Workload Identity Federation) | Project owner |
| [ ] | Real Gemini extraction on hand-written notebooks; record fixtures | Vertex AI or Gemini API key |
| [ ] | Cloud Storage buckets (evidence; audit packs with Bucket Lock), Firestore | Project |
| [ ] | Cloud KMS Ed25519 key for signing audit packs | Project |
| [ ] | Train the risk model in BigQuery ML and export weights | Project |
| [ ] | RAG Engine corpus with regulator PDFs | Project, PDFs |
| [ ] | Model Armor template on agent traffic | Project |
| [ ] | Deploy API, web and A2A to Cloud Run (`dev`), agents to Agent Runtime | All of the above |
| [ ] | `demo` environment promoted and frozen (Sat 17) | Deployed `dev` |

## Phase 3: submission (Sat 17 – Sun 18 October 2026)

| Status | # | Item | Priority |
|---|---|---|---|
| [ ] | 23 | Demo video and backup clips | P0 |
| [ ] | 24 | Submission write-up and architecture diagram | P0 |
| [ ] | 26 | Submit, then verify the submission opens correctly; tag `v0.1.0-buildercup` | P0 |
| [ ] | — | Licence chosen and added | Decision pending |

## Decisions and changes to the plan

| Date | Change | Why |
|---|---|---|
| 2026-10-12 | `main` + `dev` with feature branches from `dev`; no approval required to merge | Owner's workflow; small team |
| 2026-10-12 | Build fully locally first with offline adapters; cloud wired behind settings | Cloud accounts not yet provided |
| 2026-10-12 | Risk model trained on synthetic applicants and marked illustrative | No public dataset of notebook-evidenced loans |
| 2026-10-12 | Audit packs signed with Ed25519 (KMS in the cloud) | A hash chain alone can be rebuilt by anyone |
| 2026-10-12 | Live voice interview deferred | Playbook cut line; needs credentials to test |
