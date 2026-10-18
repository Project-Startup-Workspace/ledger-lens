#!/usr/bin/env bash
# One-time Google Cloud setup for Ledger Lens. Safe to re-run: existing resources are kept.
#
# Usage: infra/gcp/bootstrap.sh <project-id> <github-owner/repo> [region]
# Needs: gcloud signed in as a project Owner, and billing linked to the project.
set -euo pipefail

PROJECT="${1:?project id, e.g. ledger-lens-dev}"
REPO="${2:?GitHub repository, e.g. Project-Startup-Workspace/ledger-lens}"
REGION="${3:-asia-southeast1}"
PREFIX="${PROJECT}"
EVIDENCE_BUCKET="${PREFIX}-evidence"
AUDIT_BUCKET="${PREFIX}-audit-packs"
AUDIT_RETENTION="${AUDIT_RETENTION:-7y}"   # lending records; confirm with counsel
KEYRING="ledger-lens"
KEY="audit-signing"
RUNTIME_SA="ledger-lens-runtime@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="ledger-lens-deploy@${PROJECT}.iam.gserviceaccount.com"
WEB_SA="ledger-lens-web@${PROJECT}.iam.gserviceaccount.com"  # secrets only

g() { gcloud --project="$PROJECT" "$@"; }
exists() { "$@" >/dev/null 2>&1; }
step() { printf '\n== %s\n' "$*"; }

step "Enable APIs"
g services enable \
  aiplatform.googleapis.com run.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com firestore.googleapis.com bigquery.googleapis.com \
  secretmanager.googleapis.com cloudkms.googleapis.com modelarmor.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com cloudbuild.googleapis.com

step "Artifact Registry for container images"
exists g artifacts repositories describe ledger-lens --location="$REGION" ||
  g artifacts repositories create ledger-lens --repository-format=docker --location="$REGION"

step "Firestore (case files and audit events)"
exists g firestore databases describe --database='(default)' ||
  g firestore databases create --location="$REGION" --type=firestore-native

step "Buckets: evidence, and audit packs with a retention policy"
exists gcloud storage buckets describe "gs://$EVIDENCE_BUCKET" ||
  g storage buckets create "gs://$EVIDENCE_BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
exists gcloud storage buckets describe "gs://$AUDIT_BUCKET" ||
  g storage buckets create "gs://$AUDIT_BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention --retention-period="$AUDIT_RETENTION"
echo "Bucket Lock is permanent, so it is not applied automatically. When ready:"
echo "  gcloud storage buckets update gs://$AUDIT_BUCKET --lock-retention-period"

step "KMS Ed25519 key that signs audit packs"
exists g kms keyrings describe "$KEYRING" --location="$REGION" ||
  g kms keyrings create "$KEYRING" --location="$REGION"
exists g kms keys describe "$KEY" --keyring="$KEYRING" --location="$REGION" ||
  g kms keys create "$KEY" --keyring="$KEYRING" --location="$REGION" \
    --purpose=asymmetric-signing --default-algorithm=ec-sign-ed25519

step "BigQuery dataset for the risk model"
exists bq --project_id="$PROJECT" show ledger_lens ||
  bq --project_id="$PROJECT" mk --dataset --location="$REGION" ledger_lens

step "Service accounts"
for sa in ledger-lens-runtime ledger-lens-web ledger-lens-deploy; do
  exists g iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" ||
    g iam service-accounts create "$sa" --display-name="$sa"
done

step "Runtime permissions (least privilege)"
for role in roles/aiplatform.user roles/datastore.user roles/modelarmor.user \
  roles/bigquery.dataViewer roles/bigquery.jobUser roles/logging.logWriter; do
  g projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$RUNTIME_SA" \
    --role="$role" --condition=None >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$EVIDENCE_BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectAdmin >/dev/null
# Audit packs: create only. Nothing at runtime may overwrite or delete them.
gcloud storage buckets add-iam-policy-binding "gs://$AUDIT_BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectCreator >/dev/null
g kms keys add-iam-policy-binding "$KEY" --keyring="$KEYRING" --location="$REGION" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudkms.signerVerifier >/dev/null

step "Deploy permissions"
for role in roles/run.admin roles/artifactregistry.writer roles/aiplatform.user; do
  g projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY_SA" \
    --role="$role" --condition=None >/dev/null
done
for sa in "$RUNTIME_SA" "$WEB_SA"; do
  g iam service-accounts add-iam-policy-binding "$sa" \
    --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser >/dev/null
done

step "Keyless GitHub deploys (Workload Identity Federation)"
PROJECT_NUMBER="$(g projects describe "$PROJECT" --format='value(projectNumber)')"
exists g iam workload-identity-pools describe github --location=global ||
  g iam workload-identity-pools create github --location=global --display-name="GitHub"
# Only this repository's main and dev branches may mint deploy credentials. The
# condition is (re)applied on every run, so re-running tightens an existing provider.
WIF_MAPPING="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref"
WIF_CONDITION="assertion.repository=='${REPO}' && (assertion.ref=='refs/heads/main' || assertion.ref=='refs/heads/dev')"
if exists g iam workload-identity-pools providers describe github --workload-identity-pool=github --location=global; then
  g iam workload-identity-pools providers update-oidc github --location=global \
    --workload-identity-pool=github --attribute-mapping="$WIF_MAPPING" \
    --attribute-condition="$WIF_CONDITION"
else
  g iam workload-identity-pools providers create-oidc github --location=global \
    --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="$WIF_MAPPING" --attribute-condition="$WIF_CONDITION"
fi
g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}" >/dev/null

cat <<OUT

Done. Set these GitHub repository variables (Settings → Secrets and variables → Actions → Variables):
  GCP_PROJECT     = $PROJECT
  GCP_REGION      = $REGION
  WIF_PROVIDER    = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github
  DEPLOY_SA       = $DEPLOY_SA
  RUNTIME_SA      = $RUNTIME_SA
  WEB_SA          = $WEB_SA
  EVIDENCE_BUCKET = $EVIDENCE_BUCKET
  AUDIT_BUCKET    = $AUDIT_BUCKET
  AUDIT_KMS_KEY   = projects/$PROJECT/locations/$REGION/keyRings/$KEYRING/cryptoKeys/$KEY/cryptoKeyVersions/1

Still manual: a billing budget alert (Billing → Budgets & alerts), a Model Armor template,
the RAG Engine corpus with regulator PDFs, and the ll-api-token and ll-web-users secrets
(see infra/README.md).
OUT
