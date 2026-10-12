# 0003. Train the risk model in BigQuery ML, score from exported weights

- Status: accepted
- Date: 2026-10-12

## Context
Lenders and regulators (for example MAS's AI risk guidelines) expect credit scores to be explainable, validated and reproducible. We have no real repayment outcomes yet.

## Decision
- Use logistic regression: its Shapley values are exact (`coefficient × standardised value`), so each reason code is exactly true.
- Train in BigQuery ML (SQL, `ML.EXPLAIN_PREDICT`, `ML.EVALUATE`). Export weights and feature statistics to a versioned JSON artifact.
- Score inside the agent from that artifact. The same artifact format is produced by local training on synthetic data.

## Consequences
- Scoring is offline, fast and identical everywhere. Model upgrades are a reviewed artifact change.
- Linear effects only. Caps (such as coverage at 5×) keep the fit honest at the extremes.
- A boosted-tree model would need sampled Shapley values and a different counterfactual search. We revisit this once pilots provide outcome data.
