-- Per-applicant Shapley attributions, then approval rate by group (four-fifths rule).
-- An applicant counts as approved when the predicted probability of default is below 10%.
WITH scored AS (
  SELECT
    group_attr,
    (SELECT prob FROM UNNEST(predicted_defaulted_probs) WHERE label = 1) AS p_default,
    top_feature_attributions
  FROM ML.EXPLAIN_PREDICT(
    MODEL `ledger_lens.risk_model_v1`,
    (SELECT * FROM `ledger_lens.synthetic_applicants`),
    STRUCT(7 AS top_k_features)
  )
)
SELECT
  group_attr,
  COUNT(*) AS applicants,
  AVG(IF(p_default < 0.10, 1, 0)) AS approval_rate
FROM scored
GROUP BY group_attr;
