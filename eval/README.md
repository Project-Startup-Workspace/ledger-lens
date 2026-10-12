# Evaluation

Two questions, answered on every model or prompt change:

1. **Does the evidence agent read notebooks correctly in each script?** Labelled pages are in `demo-data/*/labels/`.
2. **Does the risk model treat groups fairly?** Approval rates by a group attribute that is never a model input, with the four-fifths rule.

## Run

```bash
make eval                                          # offline: scores the recorded responses
LL_LLM_PROVIDER=vertex LL_GCP_PROJECT=... make eval  # scores live Gemini reads
```

Writes `results/latest.md`, `results/latest.json` and the bias report next to the model artifact (`ml/artifacts/<version>.bias.json`).

## Metrics

| Metric | Meaning |
|---|---|
| Found | Labelled lines matched by an extracted line with the same date and direction |
| Exact amount | Matched lines read with exactly the labelled amount |
| Sent to review | Extracted lines below `LL_MIN_EXTRACTION_CONFIDENCE`, excluded from totals |
| Language detected | Pages whose language the model identified as labelled |
| Wrong but confident | Lines above the threshold with a wrong amount, or matching no labelled line (invented, wrong date or direction): the errors that reach the totals. Target 0 |

Matching pairs exact amounts first, then the closest remaining amount on the same date and direction.

Fairness is measured on the **holdout** applicants only (`is_holdout` in the training CSV), using the risk agent's own approval grades (A, B). The bias report records the artifact's fingerprint; AuditPulse rule `SG-BIA-01` accepts it only if it passed and matches the active model, so retraining requires a fresh `make eval`.

`make eval` exits non-zero when a gate fails (any confident error, or a four-fifths ratio below 0.8), so the nightly workflow turns red.

## Current results

See [`results/latest.md`](results/latest.md). The committed results use the **offline** recorded responses (each demo page has one deliberately blurred amount), so they show the harness working, not Gemini's accuracy. Rerun with a Gemini provider on hand-written notebooks before quoting numbers.

Labels for new pages: add `labels/<page>.json` with `image`, `script` and `entries` (date, amount, direction), in the same format as the existing ones.
