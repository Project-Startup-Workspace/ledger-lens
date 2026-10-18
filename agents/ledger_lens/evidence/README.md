# Evidence agent

Reads one uploaded document into `LedgerEntry` records and calculates weekly cash flow.

| | |
|---|---|
| Input | `EvidenceDocument` + file bytes, case reference date, expected currency |
| Output | `ExtractionResult` (entries with confidence and bounding boxes); `CashFlowSummary` via `tools.weekly_cash_flow` |
| Model | `LL_MODEL_EXTRACT` (default Gemini 3.8 Flash) with the `WireExtraction` response schema |
| Deterministic | CSV wallet/bank exports, all totals and averages, date and amount validation |

How it stays trustworthy:
- Gemini only reads. Python does every sum, so totals are reproducible.
- Lines below `LL_MIN_EXTRACTION_CONFIDENCE` are excluded from totals and queued for the officer.
- Each amount carries the box it was read from, so the UI can show its source on the photo.
- Page text is screened for prompt injection; flagged pages get a warning on the case.

Known limits:
- Dates without a year are resolved against the case date; notebooks spanning New Year need a check.
- One page per call. Multi-page PDFs should be split before upload.
