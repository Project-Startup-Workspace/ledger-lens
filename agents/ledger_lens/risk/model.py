"""A logistic-regression risk model stored as plain JSON, with exact Shapley attributions.

For a linear model on standardised, independent features, feature i's Shapley value in
log-odds is coefficient_i * z_i: the same quantity BigQuery ML's ML.EXPLAIN_PREDICT
reports, so local and cloud scoring explain themselves identically.
"""

import json
import math
from pathlib import Path

from pydantic import BaseModel


class LogisticModel(BaseModel):
    version: str
    features: list[str]
    means: list[float]
    scales: list[float]
    coefficients: list[float]  # per standardised feature, in log-odds of default
    intercept: float
    trained_on: str
    metrics: dict[str, float]
    illustrative: bool = True

    def standardise(self, values: dict[str, float]) -> list[float]:
        return [
            (values[name] - mean) / scale
            for name, mean, scale in zip(self.features, self.means, self.scales, strict=True)
        ]

    def logit(self, values: dict[str, float]) -> float:
        z = self.standardise(values)
        return self.intercept + sum(c * v for c, v in zip(self.coefficients, z, strict=True))

    def probability(self, values: dict[str, float]) -> float:
        return 1 / (1 + math.exp(-self.logit(values)))

    def attributions(self, values: dict[str, float]) -> dict[str, float]:
        """Shapley value of each feature, relative to the average training applicant."""
        z = self.standardise(values)
        return {name: c * v for name, c, v in zip(self.features, self.coefficients, z, strict=True)}

    def value_for_logit(self, values: dict[str, float], feature: str, target: float) -> float:
        """Value `feature` would need, others unchanged, for the logit to reach `target`."""
        i = self.features.index(feature)
        gap = target - self.logit(values)
        return values[feature] + gap / self.coefficients[i] * self.scales[i]

    @classmethod
    def load(cls, path: Path) -> "LogisticModel":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
