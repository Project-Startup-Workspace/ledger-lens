# Demo data (synthetic)

Every person, business, ID number and figure in this folder is invented. No real borrower data is ever committed.

| Case | Script | Currency | What it shows |
|---|---|---|---|
| `synthetic-warung-jakarta` | Latin (Bahasa Indonesia) | IDR | Notebook sales inflated in week of 14 Sep; the wallet statement does not follow, so the consistency check flags it |
| `synthetic-grocer-kandy` | Sinhala | LKR | Long, steady history with a consistent wallet statement |
| `synthetic-market-stall-hcmc` | Latin (Vietnamese) | VND | Four weeks only, volatile sales, no wallet: a thin file |

Each case folder holds:
- `notebook-p*.png`: rendered notebook pages. One amount per page is blurred on purpose.
- `labels/notebook-p*.json`: ground truth for each page, used by `eval/`.
- `wallet-statement.csv`: wallet export, where the case has one.
- `case.json`: applicant and loan request used to open the case.

Each case opens under a jurisdiction that has a rule pack (`lk`, `sg`, `in`). Indonesian and Vietnamese packs come after the competition; the jurisdiction switcher shows any case under any pack.

`fixtures/` holds the recorded model response for each page, so the system runs offline. The blurred amount is recorded with low confidence and a misreading, to exercise the review queue and the accuracy report.

Regenerate everything (changes the images, so fixtures and labels are rewritten too):

```bash
cd agents && uv run python scripts/generate_demo_data.py
```

Before the live demo, replace or extend these with notebooks the team writes by hand, then record their labels.
