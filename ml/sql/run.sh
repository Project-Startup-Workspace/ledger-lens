#!/usr/bin/env bash
# Load the synthetic training data, train the BQML model and run the explain/bias query.
# Usage: ml/sql/run.sh <project> [dataset]   (dataset defaults to LL_BQ_DATASET or ledger_lens)
set -euo pipefail
PROJECT="${1:?project id}"
DATASET="${2:-${LL_BQ_DATASET:-ledger_lens}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${PROJECT}.${DATASET}"

bq --project_id="$PROJECT" mk --dataset --location=asia-southeast1 "$DATASET" 2>/dev/null || true
bq --project_id="$PROJECT" load --replace --skip_leading_rows=1 --source_format=CSV \
  "${DATASET}.synthetic_applicants" "$HERE/../data/synthetic_applicants.csv" \
  debt_service_coverage:FLOAT,sales_volatility:FLOAT,weeks_of_records:FLOAT,years_in_business:FLOAT,wallet_verified:FLOAT,mismatch_share:FLOAT,expense_ratio:FLOAT,group_attr:STRING,defaulted:INTEGER

for sql in "$HERE"/0*.sql; do
  echo "running $(basename "$sql")"
  sed "s/{{DATASET}}/${TARGET}/g" "$sql" | bq --project_id="$PROJECT" query --use_legacy_sql=false
done
