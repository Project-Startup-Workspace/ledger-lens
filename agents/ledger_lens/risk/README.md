# Risk agent

| | |
|---|---|
| Input | `CreditFile` with `cash_flow` and `consistency` filled |
| Output | `RiskResult`: probability of default, grade A–E, recommendation, top 4 reason codes, path to approval |
| Model | `LogisticModel` artifact at `LL_RISK_MODEL_PATH` (see `ml/README.md`) |

- Reason codes are exact Shapley values in log-odds, relative to the average training applicant.
- The path to approval lists single changes that would each reach grade B: more weeks of records, a matching statement, or a smaller loan. If no single change is enough, the most effective feasible changes are listed together.
- The output is a recommendation. A high-severity consistency flag downgrades "approve" to "refer".
- The result is marked `illustrative` while the model is trained on synthetic data.
