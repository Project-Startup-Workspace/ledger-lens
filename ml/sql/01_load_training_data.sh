#!/usr/bin/env bash
# Load the synthetic training rows into BigQuery. Usage: ./01_load_training_data.sh <project>
set -euo pipefail
PROJECT="${1:?project id}"
DATASET="${LL_BQ_DATASET:-ledger_lens}"
bq --project_id="$PROJECT" mk --dataset --location=asia-southeast1 "$DATASET" 2>/dev/null || true
bq --project_id="$PROJECT" load --replace --skip_leading_rows=1 --source_format=CSV \
  "$DATASET.synthetic_applicants" "$(dirname "$0")/../data/synthetic_applicants.csv" \
  debt_service_coverage:FLOAT,sales_volatility:FLOAT,weeks_of_records:FLOAT,years_in_business:FLOAT,wallet_verified:FLOAT,mismatch_share:FLOAT,expense_ratio:FLOAT,group_attr:STRING,defaulted:INTEGER
