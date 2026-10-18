# Demo script (3 minutes)

One job: show that a messy notebook becomes a decision a lender can defend, in any JAPAC market.

Before going on stage: open the web app on a phone, then open the **Warung Jakarta** and **Grocer Kandy** demo cases and assess both. Keep a recording of every step as a backup; if a live step fails, switch to the recording without comment.

| Time | Beat | On screen |
|---|---|---|
| 0:00–0:20 | **Hook.** "Three shopkeepers, three scripts, the same rejection letter." | Home: the three demo cases (Bahasa Indonesia, Sinhala, Vietnamese) |
| 0:20–1:00 | **Evidence, live.** Photograph a notebook page. Boxes light up; tap a figure to see where it came from. The blurred amount is marked for review, not guessed. | Warung Jakarta → Evidence; then Weekly cash flow |
| 1:00–1:30 | **The fraud catch.** The wallet statement disagrees with the notebook in the week of 14 Sep; the system drafts the question to ask. | Notebook vs wallet: high flag, "Ask: …" |
| 1:30–2:00 | **Risk with reasons.** Grade and top reasons; the high flag routes it to a person. Switch to Kandy for a clean approval, or Ho Chi Minh City for a "path to approval". | Risk panel |
| 2:00–2:30 | **AuditPulse.** Switch Sri Lanka → Singapore → India; the checklist changes, each item cites its rule. Record a decision, then **Export audit pack**. | Compliance; Decision; Audit trail ("chain intact") |
| 2:30–2:50 | **The borrower's side.** Play the explanation in Tamil with English subtitles. | For the borrower: Tamil (needs Gemini) |
| 2:50–3:00 | **Close.** "Built on Gemini Enterprise Agent Platform. Launching with Sri Lankan lenders under the new 2026 licensing law, designed for every JAPAC script." | — |

Before the demo, check:
- The live run uses hand-written notebooks with recorded labels (`demo-data/README.md`), not only the synthetic pages.
- `make eval` results are up to date and quoted from `eval/results/latest.md`.
- The `demo` environment is frozen (no deploys on Sunday).
