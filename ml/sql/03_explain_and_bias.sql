-- Per-applicant Shapley attributions on the holdout rows, then approval rate by group
-- (four-fifths rule).
-- ML.EXPLAIN_PREDICT returns the probability of the predicted label only, so the
-- probability of default is recovered from it. Approved means P(default) < 10%.
WITH scored AS (
  SELECT
    group_attr,
    IF(predicted_defaulted = 1, probability, 1 - probability) AS p_default,
    top_feature_attributions
  FROM ML.EXPLAIN_PREDICT(
    MODEL `{{DATASET}}.risk_model_v1`,
    (SELECT * FROM `{{DATASET}}.synthetic_applicants` WHERE is_holdout),
    STRUCT(7 AS top_k_features)
  )
)
SELECT
  group_attr,
  COUNT(*) AS applicants,
  AVG(IF(p_default < 0.10, 1, 0)) AS approval_rate
FROM scored
GROUP BY group_attr;
