# Infrastructure

Everything runs locally without cloud accounts. This folder holds what is needed to run it in containers and on Google Cloud.

## Containers (local)

```bash
docker compose up --build      # web :3000, API :8080, AuditPulse A2A :8081
```

`infra/docker/api.Dockerfile` serves both the API and the A2A service (different commands). `infra/docker/web.Dockerfile` builds the Next.js standalone server. CI builds both images on every pull request.

## Google Cloud (dev environment)

| Service | Used for |
|---|---|
| Cloud Run | `ledger-lens-web`, `ledger-lens-api`, `ledger-lens-a2a` |
| Gemini Enterprise Agent Platform (Vertex AI) | Gemini extraction, explanations, TTS; Agent Runtime for the ADK workflow; RAG Engine |
| Firestore | Case files and audit events (transactional appends) |
| Cloud Storage | Evidence files; audit packs in a bucket with a retention policy (Bucket Lock) |
| Cloud KMS | Ed25519 key that signs audit packs |
| BigQuery ML | Training the risk model (`ml/sql/run.sh`) |
| Model Armor | Screening text read from uploaded documents |
| Secret Manager | `ll-api-token` shared by the web app and the API |
| Artifact Registry | Container images |

### One-time setup

1. Create a project (for example `ledger-lens-dev`), link billing and add a budget alert.
2. Run, as a project Owner:

   ```bash
   infra/gcp/bootstrap.sh ledger-lens-dev Project-Startup-Workspace/ledger-lens asia-southeast1
   ```

   It enables the APIs and creates the registry, Firestore, buckets, KMS key, BigQuery dataset, two least-privilege service accounts and keyless GitHub access (Workload Identity Federation). It ends by printing the GitHub repository variables to set.
3. Create the API token secret:

   ```bash
   openssl rand -hex 32 | gcloud secrets create ll-api-token --data-file=- --project ledger-lens-dev
   gcloud secrets add-iam-policy-binding ll-api-token --project ledger-lens-dev \
     --member serviceAccount:ledger-lens-runtime@ledger-lens-dev.iam.gserviceaccount.com \
     --role roles/secretmanager.secretAccessor
   ```

4. Create the web sign-in users (one `name:password` per officer, comma separated):

   ```bash
   printf 'priya:CHANGE-ME,ravi:CHANGE-ME' | gcloud secrets create ll-web-users --data-file=- --project ledger-lens-dev
   gcloud secrets add-iam-policy-binding ll-web-users --project ledger-lens-dev \
     --member serviceAccount:ledger-lens-runtime@ledger-lens-dev.iam.gserviceaccount.com \
     --role roles/secretmanager.secretAccessor
   ```

   For production, put the web app behind Identity-Aware Proxy instead and leave `LL_WEB_USERS` unset.

5. Optional: create a Model Armor template and a RAG Engine corpus with the regulator PDFs, then set `LL_MODEL_ARMOR_TEMPLATE`, `LL_RAG_CORPUS` and the matching `*_BACKEND=gcp` settings.
6. Merge `dev` into `main`. `.github/workflows/deploy.yml` builds, pushes and deploys all three services.

Access: the web app signs officers in; the API admits traffic at the Cloud Run layer and requires the shared token itself (Cloud Run IAM would otherwise claim the same `Authorization` header); the A2A service requires Google identity tokens.

Never put a service-account JSON key in GitHub or in this repo. CI signs in through Workload Identity Federation.

### Agent Runtime (optional)

`ledger_lens.adk_app.root_agent` is an ADK `Workflow` running the five stages. Deploy it with the ADK CLI's Agent Runtime deploy command from `agents/` (check the current ADK docs for the exact command), using the same `LL_*` settings as the API.
