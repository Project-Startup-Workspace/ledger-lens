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
| Firebase Hosting | The public link (`<project>.web.app`); forwards every request to `ledger-lens-web` |
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
   # tr strips the newline, which would otherwise become part of the token
   openssl rand -hex 32 | tr -d '\n' | gcloud secrets create ll-api-token --data-file=- --project ledger-lens-dev
   for sa in ledger-lens-runtime ledger-lens-web; do
     gcloud secrets add-iam-policy-binding ll-api-token --project ledger-lens-dev \
       --member serviceAccount:$sa@ledger-lens-dev.iam.gserviceaccount.com \
       --role roles/secretmanager.secretAccessor
   done
   ```

4. Sign-in. With Firebase Authentication (the default once `FIREBASE_API_KEY` is set), run `infra/gcp/firebase-auth.sh <project-id>` (bootstrap runs it too), set the `FIREBASE_API_KEY` variable it prints, then create the platform admin and the default lender, which keeps the cases created before organisations:

   ```bash
   cd agents
   export LL_GCP_PROJECT=ledger-lens-dev LL_STORAGE_BACKEND=gcp LL_IDENTITY_BACKEND=gcp
   uv run python -m ledger_lens.organisations platform-admin --email you@example.com
   uv run python -m ledger_lens.organisations default-lender --name "Demo Microfinance"
   uv run python -m ledger_lens.organisations add-member --org org_demo_lender --email officer@example.com --role loan_officer
   ```

   Each command asks for the new account's password. The platform admin then adds or approves lenders and audit firms in the app; their admins add their own staff; businesses sign up themselves. The commands use your Application Default Credentials (`gcloud auth application-default login`).

   Without Firebase, create HTTP Basic sign-in users instead (one `name:password` per officer, comma separated):

   ```bash
   printf 'priya:CHANGE-ME,ravi:CHANGE-ME' | gcloud secrets create ll-web-users --data-file=- --project ledger-lens-dev
   gcloud secrets add-iam-policy-binding ll-web-users --project ledger-lens-dev \
     --member serviceAccount:ledger-lens-web@ledger-lens-dev.iam.gserviceaccount.com \
     --role roles/secretmanager.secretAccessor
   ```

   For production, put the web app behind Identity-Aware Proxy instead and leave `LL_WEB_USERS` unset.

5. Optional: create a Model Armor template and a RAG Engine corpus with the regulator PDFs, then set `LL_MODEL_ARMOR_TEMPLATE`, `LL_RAG_CORPUS` and the matching `*_BACKEND=gcp` settings.
6. Merge `dev` into `main`. Once CI passes on `main`, `.github/workflows/deploy.yml` builds, pushes and deploys all three services.

Service accounts: `ledger-lens-runtime` (API, A2A) holds data, model and signing roles; `ledger-lens-web` (the internet-facing web app) can only read its two secrets.

Identity-Aware Proxy (production): put the web app behind IAP and set the `IAP_AUDIENCE` repository variable to the backend service's audience; the deploy then sets `LL_IAP_AUDIENCE` and stops injecting the Basic sign-in users. The app then verifies IAP's signed assertion for every request; it never trusts a plain identity header. Restrict the Cloud Run ingress to the load balancer so IAP cannot be bypassed.

Firebase Hosting (`infra/firebase/firebase.json`) serves only `robots.txt` itself and rewrites everything else to `ledger-lens-web`; the deploy publishes it after the web service. The sign-in proxy marks every response it gates `private, no-store`, so the Hosting CDN never caches a signed-in page.

Access: the web app signs people in with Firebase Authentication, and the API verifies the same ID token and applies each role; the API admits traffic at the Cloud Run layer and requires the shared token itself (Cloud Run IAM would otherwise claim the same `Authorization` header); the A2A service requires Google identity tokens.

Cost limits: each service is capped at 2 instances (A2A at 1), and the API allows 300 Gemini calls per UTC day across all instances (about 50 assessments), returning 429 once they are used. Spoken explanations are saved, so replaying one is free. The platform admin can change the cap in the app (Platform settings) without a redeploy; the `DAILY_MODEL_CALLS` repository variable sets the starting value. A billing budget only sends alerts; it does not stop spending.

Never put a service-account JSON key in GitHub or in this repo. CI signs in through Workload Identity Federation.

### Agent Runtime (optional)

`ledger_lens.adk_app.root_agent` is an ADK `Workflow` running the five stages. Deploy it with the ADK CLI's Agent Runtime deploy command from `agents/` (check the current ADK docs for the exact command), using the same `LL_*` settings as the API.
