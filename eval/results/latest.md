# Evaluation results

Provider: `offline`. Regenerate with `make eval`.

## Read accuracy per script

| Script (language) | Pages | Lines | Found | Exact amount | Sent to review | Language detected | Wrong but confident |
|---|---|---|---|---|---|---|---|
| Latin (id) | 4 | 69 | 100% | 94% | 6% | 100% | 0 |
| Latin (vi) | 2 | 36 | 100% | 94% | 6% | 100% | 0 |
| Sinhala (si) | 4 | 71 | 100% | 94% | 6% | 100% | 0 |

## Fairness: `risk-local-v1` (holdout rows)

| Group | Applicants | Approval rate | Mean PD |
|---|---|---|---|
| group_a | 598 | 35.8% | 18.6% |
| group_b | 602 | 34.9% | 19.0% |

Four-fifths ratio 0.97: passes.
