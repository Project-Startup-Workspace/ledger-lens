# Ledger Lens web

Mobile-first Next.js app with a view for each role: business owners see insights and share their records, loan officers prepare applications, credit reviewers decide, audit firms record findings and approve reports, and the platform admin manages organisations. Every figure is boxed where it was read on the notebook page.

## Run

```bash
npm ci
npm run dev        # http://localhost:3000 (expects the API on :8080: `make api`)
```

| Variable                                     | Meaning                                                             | Default                        |
| -------------------------------------------- | ------------------------------------------------------------------- | ------------------------------ |
| `LL_API_URL`                                 | Ledger Lens API base URL                                            | `http://localhost:8080`        |
| `LL_API_TOKEN`                               | Bearer token for the API, if it requires one                        | unset                          |
| `LL_FIREBASE_PROJECT`, `LL_FIREBASE_API_KEY` | Turn on Firebase sign-in; the browser reads them from `/api/config` | unset (no sign-in, one lender) |
| `LL_FIREBASE_AUTH_DOMAIN`                    | Auth domain, if not `<project>.firebaseapp.com`                     | unset                          |
| `FIREBASE_AUTH_EMULATOR_HOST`                | Use the Firebase Auth emulator (tests only)                         | unset                          |
| `LL_WEB_USERS`, `LL_IAP_AUDIENCE`            | Alternatives to Firebase: HTTP Basic users, or Identity-Aware Proxy | unset                          |
| `LL_OFFICER_ID`                              | Name recorded on actions when no sign-in is used                    | `officer`                      |

These are server-only: the browser calls `/api/ll/*`, a route handler that forwards to the API with the token and the signed-in person's ID token (`src/app/api/ll/[...path]/route.ts`).

## Structure

- `src/app`: routes (home per role, sign-in and sign-up, team, new case, case workspace) and the API proxy
- `src/components`: one panel per agent (evidence, cash flow, consistency, risk, compliance, explanation, decision and audit), plus sharing, requests, credit review and audit engagement
- `src/lib`: typed API client, types mirroring the Python contracts, and permissions mirroring `agents/ledger_lens/access.py`

## Checks

```bash
npm run lint && npm run typecheck && npm run format:check && npm run build
```
