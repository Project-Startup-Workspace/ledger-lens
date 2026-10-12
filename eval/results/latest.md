# Evaluation results

Provider: `offline`. Regenerate with `make eval`.

## Read accuracy per script

| Script (language) | Pages | Lines | Found | Exact amount | Sent to review | Wrong but confident |
|---|---|---|---|---|---|---|
| Latin (id) | 4 | 69 | 100% | 94% | 6% | 0 |
| Latin (vi) | 2 | 36 | 100% | 94% | 6% | 0 |
| Sinhala (si) | 4 | 71 | 100% | 94% | 6% | 0 |

## Fairness: `risk-local-v1`

| Group | Applicants | Approval rate | Mean PD |
|---|---|---|---|
| group_a | 3064 | 34.6% | 18.2% |
| group_b | 2936 | 35.6% | 18.3% |

Four-fifths ratio 0.97: passes.
