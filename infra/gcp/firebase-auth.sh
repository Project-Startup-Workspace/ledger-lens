#!/usr/bin/env bash
# Firebase Authentication for Ledger Lens: email and password sign-in, a registered web
# app, and the API's right to manage accounts. Safe to re-run.
#
# Usage: infra/gcp/firebase-auth.sh <project-id>
# Needs: gcloud signed in as a project Owner; Firebase already added (bootstrap.sh).
set -euo pipefail

PROJECT="${1:?project id, e.g. ledger-lens-dev}"
RUNTIME_SA="ledger-lens-runtime@${PROJECT}.iam.gserviceaccount.com"
ADMIN_API="https://identitytoolkit.googleapis.com/admin/v2/projects/$PROJECT"
FIREBASE_API="https://firebase.googleapis.com/v1beta1/projects/$PROJECT"

api() {
  curl -sf -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "x-goog-user-project: $PROJECT" -H "Content-Type: application/json" "$@"
}
step() { printf '\n== %s\n' "$*"; }

step "Identity Toolkit API"
gcloud --project="$PROJECT" services enable identitytoolkit.googleapis.com

step "Authentication, with email and password sign-in"
api "$ADMIN_API/config" >/dev/null ||
  api -X POST -d '{}' "https://identitytoolkit.googleapis.com/v2/projects/$PROJECT/identityPlatform:initializeAuth" >/dev/null
api -X PATCH -d '{"signIn":{"email":{"enabled":true,"passwordRequired":true}}}' \
  "$ADMIN_API/config?updateMask=signIn.email" >/dev/null

step "Web app registration"
app_id() { api "$FIREBASE_API/webApps" | python3 -c 'import json,sys; a=json.load(sys.stdin).get("apps",[]); print(a[0]["appId"] if a else "")'; }
APP_ID="$(app_id)"
if [ -z "$APP_ID" ]; then
  api -X POST -d '{"displayName":"Ledger Lens web"}' "$FIREBASE_API/webApps" >/dev/null
  for _ in $(seq 1 30); do APP_ID="$(app_id)"; [ -n "$APP_ID" ] && break; sleep 2; done
fi
API_KEY="$(api "$FIREBASE_API/webApps/$APP_ID/config" | python3 -c 'import json,sys; print(json.load(sys.stdin)["apiKey"])')"

step "The API creates accounts and sets roles"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$RUNTIME_SA" \
  --role=roles/firebaseauth.admin --condition=None >/dev/null

cat <<OUT

Done. Set this GitHub repository variable; the next deploy switches sign-in to Firebase.
(A Firebase web API key identifies the project to browsers; it is not a secret.)
  FIREBASE_API_KEY = $API_KEY
OUT
