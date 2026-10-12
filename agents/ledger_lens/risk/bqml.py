"""Export a BigQuery ML logistic-regression model into the local `LogisticModel` format.

The model is trained in BigQuery (see ml/sql) and served from exported weights. Scoring
then needs no network call, and local and cloud explanations are computed identically.
"""

import re

from google.cloud import bigquery

from ledger_lens.risk.features import FEATURE_NAMES
from ledger_lens.risk.model import LogisticModel

# Model names cannot be query parameters, so they are validated before interpolation.
_MODEL_REF = re.compile(r"^[a-z][a-z0-9-]{4,29}\.\w+\.\w+$")


def export_model(client: bigquery.Client, model_ref: str, version: str) -> LogisticModel:
    """Read standardised weights and feature statistics from a trained BQML model.

    `model_ref` is `project.dataset.model`. BQML standardises numeric inputs itself,
    so ML.WEIGHTS with standardize=TRUE pairs with ML.FEATURE_INFO's mean and stddev.
    """
    if not _MODEL_REF.match(model_ref):
        raise ValueError(f"not a project.dataset.model reference: {model_ref!r}")
    weights = {
        row["processed_input"]: row["weight"]
        for row in client.query(
            f"SELECT processed_input, weight FROM ML.WEIGHTS(MODEL `{model_ref}`, "  # noqa: S608
            "STRUCT(TRUE AS standardize))"
        ).result()
    }
    info = {
        row["input"]: (row["mean"], row["stddev"])
        for row in client.query(
            f"SELECT input, mean, stddev FROM ML.FEATURE_INFO(MODEL `{model_ref}`)"  # noqa: S608
        ).result()
    }
    query = f"SELECT roc_auc FROM ML.EVALUATE(MODEL `{model_ref}`)"  # noqa: S608
    evaluation = next(iter(client.query(query).result()))
    return LogisticModel(
        version=version,
        features=list(FEATURE_NAMES),
        means=[info[name][0] for name in FEATURE_NAMES],
        scales=[info[name][1] for name in FEATURE_NAMES],
        coefficients=[weights[name] for name in FEATURE_NAMES],
        intercept=weights["__INTERCEPT__"],
        trained_on=f"BigQuery ML model {model_ref}",
        metrics={"holdout_auc": float(evaluation["roc_auc"])},
    )
