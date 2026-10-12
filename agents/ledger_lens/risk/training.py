"""Train the local, illustrative risk model on synthetic applicants.

There is no public dataset of notebook-evidenced microloans, so this generates
applicants from a stated set of assumptions. The resulting model demonstrates the
mechanics (scores, reasons, counterfactuals, bias checks); it is not a credit model.
Pilots replace it with one trained on real, consented repayment outcomes.

Run: `cd agents && uv run python -m ledger_lens.risk.training`
"""

import csv
import json

import numpy as np
from numpy.typing import NDArray

from ledger_lens.risk.features import FEATURE_NAMES, MAX_COVERAGE
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.config import REPO_ROOT

VERSION = "risk-local-v1"
ARTIFACT = REPO_ROOT / "ml" / "artifacts" / f"{VERSION}.json"
TRAINING_CSV = REPO_ROOT / "ml" / "data" / "synthetic_applicants.csv"
SEED = 20261012

# Assumed effect of each feature on the log-odds of default in the synthetic population.
TRUE_EFFECTS = {
    "debt_service_coverage": -0.9,
    "sales_volatility": 2.2,
    "weeks_of_records": -0.035,
    "years_in_business": -0.07,
    "wallet_verified": -0.6,
    "mismatch_share": 4.0,
    "expense_ratio": 2.0,
}
TRUE_INTERCEPT = -1.6


def synthesise(
    n: int, rng: np.random.Generator
) -> tuple[NDArray[np.float64], NDArray[np.int_], NDArray[np.str_]]:
    """Return features, default labels and a synthetic group attribute for bias checks."""
    verified = rng.random(n) < 0.55
    columns = {
        "debt_service_coverage": np.minimum(rng.lognormal(np.log(1.6), 0.55, n), MAX_COVERAGE),
        "sales_volatility": rng.uniform(0.03, 0.8, n),
        "weeks_of_records": rng.integers(2, 53, n).astype(float),
        "years_in_business": np.minimum(rng.exponential(5, n), 30),
        "wallet_verified": verified.astype(float),
        "mismatch_share": np.where(verified, rng.beta(1, 7, n), 0.0),
        "expense_ratio": rng.uniform(0.45, 0.98, n),
    }
    x = np.column_stack([columns[name] for name in FEATURE_NAMES])
    effects = np.array([TRUE_EFFECTS[name] for name in FEATURE_NAMES])
    logit = TRUE_INTERCEPT + x @ effects + rng.normal(0, 0.4, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    group = rng.choice(np.array(["group_a", "group_b"]), n)  # independent of risk by design
    return x, y, group


def fit_logistic(
    x: NDArray[np.float64], y: NDArray[np.int_], l2: float = 1.0
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], float]:
    """Ridge-penalised logistic regression by Newton's method on standardised features."""
    means, scales = x.mean(axis=0), x.std(axis=0)
    z = np.column_stack([np.ones(len(x)), (x - means) / scales])
    beta = np.zeros(z.shape[1])
    penalty = np.eye(z.shape[1]) * l2
    penalty[0, 0] = 0  # never shrink the intercept
    for _ in range(50):
        p = 1 / (1 + np.exp(-z @ beta))
        gradient = z.T @ (p - y) + penalty @ beta
        hessian = (z.T * (p * (1 - p))) @ z + penalty
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    return means, scales, beta[1:], float(beta[0])


def auc(scores: NDArray[np.float64], labels: NDArray[np.int_]) -> float:
    """Area under the ROC curve via the rank-sum identity."""
    ranks = scores.argsort().argsort() + 1
    positives = labels.sum()
    negatives = len(labels) - positives
    return float(
        (ranks[labels == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives)
    )


def train(n: int = 6000) -> LogisticModel:
    rng = np.random.default_rng(SEED)
    x, y, group = synthesise(n, rng)
    split = int(n * 0.8)
    means, scales, coefficients, intercept = fit_logistic(x[:split], y[:split])
    z_test = (x[split:] - means) / scales
    test_scores = 1 / (1 + np.exp(-(intercept + z_test @ coefficients)))
    write_training_csv(x, y, group)
    return LogisticModel(
        version=VERSION,
        features=list(FEATURE_NAMES),
        means=means.round(6).tolist(),
        scales=scales.round(6).tolist(),
        coefficients=coefficients.round(6).tolist(),
        intercept=round(intercept, 6),
        trained_on=f"{n} synthetic applicants, seed {SEED}",
        metrics={
            "holdout_auc": round(auc(test_scores, y[split:]), 4),
            "default_rate": round(float(y.mean()), 4),
        },
    )


def write_training_csv(
    x: NDArray[np.float64], y: NDArray[np.int_], group: NDArray[np.str_]
) -> None:
    """The same rows, for training the cloud model with BigQuery ML (see ml/sql)."""
    TRAINING_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TRAINING_CSV.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([*FEATURE_NAMES, "group_attr", "defaulted"])
        for row, label, attr in zip(x.round(4).tolist(), y.tolist(), group.tolist(), strict=True):
            writer.writerow([*row, attr, label])


def main() -> None:
    model = train()
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(model.model_dump(), indent=2) + "\n")
    print(f"wrote {ARTIFACT.relative_to(REPO_ROOT)}: {model.metrics}")


if __name__ == "__main__":
    main()
