-- Train the risk model. group_attr is excluded from the inputs and kept for bias checks.
-- {{DATASET}} is replaced with project.dataset by run.sh.
CREATE OR REPLACE MODEL `{{DATASET}}.risk_model_v1`
OPTIONS (
  model_type = 'LOGISTIC_REG',
  input_label_cols = ['defaulted'],
  l2_reg = 1.0,
  data_split_method = 'RANDOM',
  data_split_eval_fraction = 0.2,
  enable_global_explain = TRUE
) AS
SELECT
  debt_service_coverage,
  sales_volatility,
  weeks_of_records,
  years_in_business,
  wallet_verified,
  mismatch_share,
  expense_ratio,
  defaulted
FROM `{{DATASET}}.synthetic_applicants`;
