# Consistency agent

Catches the main fraud risk, a notebook written the night before, by checking it against records the applicant cannot easily fake.

| | |
|---|---|
| Input | All `ExtractionResult`s in the case |
| Output | `ConsistencyReport`: flagged weeks, each with an explanation and a question for the officer |
| Model | None. Fully deterministic |

Method:
1. Total notebook sales and wallet/bank inflows per ISO week, over the weeks both cover.
2. The applicant's usual wallet share is the median of weekly `wallet / notebook` ratios.
3. A week is flagged when its share departs from the median by more than `LL_CONSISTENCY_TOLERANCE` (default 35%). Wallet money in a week with no notebook sales is always flagged.
4. Severity: above 50% deviation is high, above 42% medium, otherwise low. The score is 1 minus the severity-weighted share of flagged weeks.

With fewer than three comparable weeks, or no statement, the status is `insufficient_data`. The risk model then treats the notebook as unverified rather than consistent.

Flags never reject an application. They tell the officer which question to ask.
