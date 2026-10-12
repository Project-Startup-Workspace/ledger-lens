# Risk model

An interpretable logistic regression. Every score comes with Shapley reason codes and a counterfactual "path to approval".

**Illustrative only.** It is trained on synthetic applicants (`data/synthetic_applicants.csv`), generated from stated assumptions in `agents/ledger_lens/risk/training.py`. Pilots replace it with outcomes from real, consented repayment data.

| Feature | Meaning | Applicant can change it |
|---|---|---|
| `debt_service_coverage` | Monthly surplus ÷ instalment, capped at 5 | Yes (borrow less) |
| `sales_volatility` | Coefficient of variation of weekly sales | No |
| `weeks_of_records` | Weeks of notebook history | Yes |
| `years_in_business` | Self-declared tenure | No |
| `wallet_verified` | A statement was compared with the notebook | Yes |
| `mismatch_share` | Share of compared weeks that were flagged; 0.125 (average) when there is no statement | No |
| `expense_ratio` | Expenses ÷ sales | No |

## Local (default)

```bash
cd agents && uv run python -m ledger_lens.risk.training
```

This writes `artifacts/risk-local-v1.json` (weights, feature means and scales, holdout AUC) and the training CSV.

## BigQuery ML

1. `sql/run.sh <project> [dataset]` loads the CSV, trains with `enable_global_explain` (`02_train_risk_model.sql`), and reports `ML.EXPLAIN_PREDICT` attributions and approval rate by group (`03_explain_and_bias.sql`).
2. Export the weights with `ledger_lens.risk.bqml.export_model`, save them as a JSON artifact, and point `LL_RISK_MODEL_PATH` at it.

Scoring always runs from an exported artifact, so a case never waits on a BigQuery query and explanations match between environments. See `docs/adr/0003-bigquery-ml-risk-model.md`.

Grades: A < 5% probability of default, B < 10%, C < 18%, D < 30%, E otherwise. A and B are recommended for approval, C for referral, and D and E for decline. A high-severity consistency flag always routes the case to an officer.
