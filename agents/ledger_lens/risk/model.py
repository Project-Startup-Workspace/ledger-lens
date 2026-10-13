"""A logistic-regression risk model stored as plain JSON, with exact Shapley attributions.

For a linear model on standardised, independent features, feature i's Shapley value in
log-odds is coefficient_i * z_i: the same quantity BigQuery ML's ML.EXPLAIN_PREDICT
reports, so local and cloud scoring explain themselves identically.
"""

import json
import math
from pathlib import Path

from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def _well_formed(self) -> "LogisticModel":
        """Reject artifacts that would divide by zero or misalign features."""
        sizes = {len(self.features), len(self.means), len(self.scales), len(self.coefficients)}
        if len(sizes) != 1:
            raise ValueError("features, means, scales and coefficients differ in length")
        if any(scale <= 0 for scale in self.scales):
            raise ValueError("every feature scale must be positive (a constant column?)")
        return self

    def standardise(self, values: dict[str, float]) -> list[float]:
        return [
            (values[name] - mean) / scale
            for name, mean, scale in zip(self.features, self.means, self.scales, strict=True)
        ]

    def logit(self, values: dict[str, float]) -> float:
        z = self.standardise(values)
        return self.intercept + sum(c * v for c, v in zip(self.coefficients, z, strict=True))

    def probability(self, values: dict[str, float]) -> float:
        """Logistic of the logit, computed so extreme inputs cannot overflow."""
        logit = self.logit(values)
        if logit >= 0:
            return 1 / (1 + math.exp(-logit))
        odds = math.exp(logit)
        return odds / (1 + odds)

    def attributions(self, values: dict[str, float]) -> dict[str, float]:
        """Shapley value of each feature, relative to the average training applicant."""
        z = self.standardise(values)
        return {name: c * v for name, c, v in zip(self.features, self.coefficients, z, strict=True)}

    def value_for_logit(
        self, values: dict[str, float], feature: str, target: float
    ) -> float | None:
        """Value `feature` would need, others unchanged, for the logit to reach `target`.

        None when the feature has no effect in this model, so no value would do it.
        """
        i = self.features.index(feature)
        if self.coefficients[i] == 0:
            return None
        gap = target - self.logit(values)
        return values[feature] + gap / self.coefficients[i] * self.scales[i]

    @classmethod
    def load(cls, path: Path) -> "LogisticModel":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
