# Ledger Lens web (officer app)

Mobile-first Next.js app that loan officers use in the field: photograph notebook pages, see every figure boxed where it was read, review the fraud check, risk reasons and compliance checklist, play the borrower's explanation, and record the decision.

## Run

```bash
npm ci
npm run dev        # http://localhost:3000 (expects the API on :8080: `make api`)
```

| Variable        | Meaning                                                                                        | Default                 |
| --------------- | ---------------------------------------------------------------------------------------------- | ----------------------- |
| `LL_API_URL`    | Ledger Lens API base URL                                                                       | `http://localhost:8080` |
| `LL_API_TOKEN`  | Bearer token for the API, if it requires one                                                   | unset                   |
| `LL_TRUST_IAP`  | `true` only when Identity-Aware Proxy fronts the app; IAP's signed-in user becomes the officer | unset                   |
| `LL_OFFICER_ID` | Officer recorded on actions until sign-in exists                                               | `officer`               |

These are server-only: the browser calls `/api/ll/*`, a route handler that forwards to the API and adds the token and officer id (`src/app/api/ll/[...path]/route.ts`).

## Structure

- `src/app`: routes (home, new case, case workspace) and the API proxy
- `src/components`: one panel per agent (evidence, cash flow, consistency, risk, compliance, explanation, decision and audit)
- `src/lib`: typed API client and types mirroring the Python contracts

## Checks

```bash
npm run lint && npm run typecheck && npm run format:check && npm run build
```
