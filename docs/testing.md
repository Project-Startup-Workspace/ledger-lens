# Testing guide

Two ways to try Ledger Lens: the deployed prototype, signed in as each role, or a local copy with no cloud account.

## Deployed prototype

Site: https://ledger-lens-512003.web.app

**Judges:** the sign-ins for each role are in the submission form. Each account already has assessed cases, so every screen can be opened without uploading anything. Use a private window per role, or sign out between them.

### Roles

| Organisation | Role | Can |
|---|---|---|
| Platform | Platform admin | Approve or suspend organisations, set the daily Gemini cap, add organisation admins; sees cases only with time-limited support access |
| Bank | Admin | Manage staff and roles; grant audit firms or platform support access |
| Bank | Loan officer | Open and prepare applications, ask the business for evidence, send a case for credit review |
| Bank | Credit reviewer | Decide the applications assigned to them, with a reason |
| Audit firm | Admin | Manage staff; assign engagements on cases the firm was granted |
| Audit firm | Audit officer | Request evidence, record findings, submit for review |
| Audit firm | Audit reviewer | Return findings or approve the final report |
| Business | Owner | See insights, submit evidence, send an application to a lender, acknowledge terms |
| Business | Accountant | Upload records and answer requests; cannot share or send |

### Setting up your own accounts

Use email addresses you can receive. With Gmail, `you+officer@gmail.com` and similar all arrive in one inbox, so "Forgot password?" works for every test account.

1. **Platform admin** (created with `python -m ledger_lens.organisations platform-admin`, see `infra/README.md`): under Platform settings, set the daily cap; add a bank admin to Demo Microfinance; add an audit firm with its first admin.
2. **Bank admin**, Team & access: add a loan officer and a credit reviewer; grant the audit firm.
3. **Audit admin**, Team & access: add an audit officer and an audit reviewer.
4. Signed out, **Create an account** → My business. Then, as the owner, Team & sharing: add an accountant.

### Use cases

Notebook pages, a wallet statement and the form values for each synthetic case are in `demo-data/` (form values in each `case.json`).

**A. The owner's own insights.** As the owner, open a new application with `demo-data/synthetic-warung-jakarta`: upload the four pages and the wallet statement, then Assess (about a minute). The home page shows the sales trend, best and weakest weeks, cost share, the flagged week (14 Sep) and loan readiness. The application is private: the loan officer cannot see it.

**B. Send and ask.** As the owner, Send to lender → Demo Microfinance; upload and Assess are then gone. As the loan officer, under Requests, ask the business about the flagged week. As the accountant, answer it. The accountant has no Send button and no Team & sharing page.

**C. Four eyes on the decision.** The loan officer has no decision button: Send for credit review → the reviewer. The credit reviewer finds it under "Sent to you for a decision" and records a decision with a reason. The owner sees the decision and the explanation in Bahasa Indonesia, with English beside it.

**D. Audit engagement.** As the audit admin, Assign engagement → the audit officer. The officer asks the lender for evidence, records a finding and submits. The audit reviewer returns it once, then approves the final report; export the audit pack, and the trail stays "chain intact". The bank admin revokes the grant, and the audit firm loses the case.

**E. Other scripts.** As the loan officer, open a case with `demo-data/synthetic-grocer-kandy` (Sinhala, Sri Lanka rules) or `synthetic-market-stall-hcmc` (Vietnamese, thin file, path to approval). Switch the borrower language and back; returning to a language already written is free.

**F. Platform controls.** Sign up as a new lender: it waits for approval. As the platform admin, approve it, then suspend it. As a bank admin, allow platform support for 24 hours: the bank's cases appear under Support access, read-only, until revoked. Turning off "Lenders and audit firms may sign up" refuses new lender sign-ups; businesses can still sign up.

**G. What must be refused.**

| Try | Expected |
|---|---|
| A loan officer opens another lender's case, or a private owner application | "not found" |
| A credit reviewer decides a case assigned to someone else | Refused |
| An audit officer opens a case not assigned to them | "not found" |
| An audit officer approves their own findings | No button; the API refuses |
| An accountant shares or grants access | No buttons; the API refuses |
| Signed out, open any page | Sent to the sign-in page |
| "Forgot password?" with any email | The same message whether or not the account exists |

Each assessment uses about 5–6 Gemini calls (one per page, plus the explanation), and speaking it uses one. Viewing, replaying audio, requests, reviews and the audit trail cost nothing. The platform page shows today's count.

## Local copy

`make setup`, `make api` and `npm run dev` (see the README) run everything offline, with recorded model responses and one lender, so no sign-in is needed. The demo cases open from the home page.

| Check | Command |
|---|---|
| Lint, types, unit and API tests, web build | `make check` |
| Firestore and Cloud Storage adapters against their emulators | `make emulators && make test-integration` |
| Extraction accuracy and fairness | see `eval/README.md` |

`agents/tests/api/test_organisations.py` covers each role's permissions end to end against the API, including the refusals in G.
