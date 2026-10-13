# Consistency agent

Catches the main fraud risk, a notebook written the night before, by checking it against a record the applicant cannot easily fake.

| | |
|---|---|
| Input | All `ExtractionResult`s in the case, and the case currency |
| Output | `ConsistencyReport`: flagged weeks, each with an explanation and a question for the officer |
| Model | None. Fully deterministic |

Method:
1. Choose one statement: the wallet or bank export with the most confidently read weeks. Summing several would double count transfers between accounts.
2. Compare only weeks that both the notebook and the statement cover from Monday to Sunday. Skip weeks where either has an unreadable line rather than treating them as low.
3. The applicant's usual wallet share is the median of weekly `wallet ÷ notebook` ratios.
4. A week is flagged when `|ln(share ÷ usual share)|` exceeds `ln(1 + LL_CONSISTENCY_TOLERANCE)`, so 2× notebook inflation and 2× wallet excess are judged equally. Severity: above 2× the threshold is high, above 1.5× medium, otherwise low.
5. Wallet money arriving in a week with no notebook sales is flagged, graded by its size against a typical week's inflow. Trivial amounts are ignored.

The status is `insufficient_data`, with `consistency_score = null`, when there is no statement, fewer than three comparable weeks, or a usual wallet share of zero. The risk model then treats the notebook as unverified, not as consistent or inconsistent.

Flags never reject an application. They tell the officer which question to ask.
