"""Risk agent: probability of default, grade, reason codes and a path to approval.

The score is a recommendation. The officer decides, and every override is logged.
"""

import logging
import math
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal

from ledger_lens.risk.features import BY_NAME, FEATURES, MAX_COVERAGE, extract_features
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.schemas import (
    CounterfactualStep,
    CreditFile,
    ReasonCode,
    RiskGrade,
    RiskResult,
)

log = logging.getLogger(__name__)

# Upper probability-of-default bound for each grade.
GRADE_BANDS: tuple[tuple[float, RiskGrade], ...] = (
    (0.05, RiskGrade.A),
    (0.10, RiskGrade.B),
    (0.18, RiskGrade.C),
    (0.30, RiskGrade.D),
)
APPROVE_GRADES = {RiskGrade.A, RiskGrade.B}
REFER_GRADES = {RiskGrade.C}
TOP_REASONS = 4
MAX_WEEKS = 52

_FORMAT: dict[str, Callable[[float], str]] = {
    "debt_service_coverage": lambda v: (
        f"surplus covers the instalment {v:.1f} times"
        if v < MAX_COVERAGE
        else f"surplus covers the instalment at least {MAX_COVERAGE:g} times"
    ),
    "sales_volatility": lambda v: f"weekly sales vary by about {v:.0%}",
    "weeks_of_records": lambda v: f"{v:.0f} weeks of records",
    "years_in_business": lambda v: f"{v:g} years in business",
    "wallet_verified": lambda v: "checked against a statement" if v else "no statement to check",
    "mismatch_share": lambda v: f"{v:.0%} of weeks disagree with the statement",
    "expense_ratio": lambda v: f"expenses are {v:.0%} of sales",
}


def grade_for(probability: float) -> RiskGrade:
    for bound, grade in GRADE_BANDS:
        if probability < bound:
            return grade
    return RiskGrade.E


class RiskAgent:
    def __init__(self, model: LogisticModel) -> None:
        self._model = model

    def assess(self, case: CreditFile) -> RiskResult:
        """Score the case and explain the score in plain words."""
        features = extract_features(case)
        probability = self._model.probability(features)
        grade = grade_for(probability)
        recommendation = (
            "approve"
            if grade in APPROVE_GRADES
            else "refer"
            if grade in REFER_GRADES
            else "decline"
        )
        # A high-severity mismatch always goes to a human, whatever the score says.
        if case.consistency and any(f.severity == "high" for f in case.consistency.flags):
            recommendation = "refer" if recommendation == "approve" else recommendation
        result = RiskResult(
            model_version=self._model.version,
            probability_of_default=round(probability, 4),
            grade=grade,
            recommendation=recommendation,
            features=features,
            reasons=self._reasons(features),
            path_to_approval=[] if grade in APPROVE_GRADES else self._path(case, features),
            illustrative=self._model.illustrative,
        )
        log.info("risk assessed", extra={"grade": grade.value, "pd": result.probability_of_default})
        return result

    def _reasons(self, features: dict[str, float]) -> list[ReasonCode]:
        contributions = self._model.attributions(features)
        ranked = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
        return [
            ReasonCode(
                feature=name,
                label=BY_NAME[name].label,
                value=features[name],
                contribution=round(value, 4),
                text=f"{_FORMAT[name](features[name]).capitalize()}, which "
                f"{'raises' if value > 0 else 'lowers'} the risk.",
            )
            for name, value in ranked[:TOP_REASONS]
        ]

    def _path(self, case: CreditFile, features: dict[str, float]) -> list[CounterfactualStep]:
        """Single changes, each enough on its own to reach grade B.

        Only features the applicant can act on are considered. If no single change is
        enough, every feasible improvement is returned, marked as not sufficient alone.
        """
        target = _logit(GRADE_BANDS[1][0] - 1e-4)
        steps = [
            step
            for feature in FEATURES
            if feature.actionable and (step := self._step(case, features, feature.name, target))
        ]
        sufficient = [s for s in steps if s.sufficient]
        return sufficient or steps

    def _step(
        self, case: CreditFile, features: dict[str, float], name: str, target: float
    ) -> CounterfactualStep | None:
        current = features[name]
        label = BY_NAME[name].label
        if name == "wallet_verified":
            if current:
                return None
            changed = {**features, "wallet_verified": 1.0, "mismatch_share": 0.0}
            return CounterfactualStep(
                feature=name,
                label=label,
                current=0,
                target=1,
                text="Add a wallet or bank statement that matches the notebook.",
                sufficient=self._model.logit(changed) <= target,
            )

        needed = self._model.value_for_logit(features, name, target)
        if name == "weeks_of_records":
            if needed <= current or current >= MAX_WEEKS:
                return None
            weeks = min(math.ceil(needed), MAX_WEEKS)
            return CounterfactualStep(
                feature=name,
                label=label,
                current=current,
                target=weeks,
                text=f"Bring {weeks - current:.0f} more weeks of records ({weeks} in total).",
                sufficient=needed <= MAX_WEEKS,
            )

        if name == "debt_service_coverage":
            if needed <= current or current <= 0 or needed > MAX_COVERAGE:
                return None
            # The instalment scales with the principal, so coverage scales inversely.
            ratio = Decimal(str(current / needed))
            amount = _round_down_to_3_figures(case.loan.amount * ratio)
            if amount < case.loan.amount * Decimal("0.1"):
                return None
            return CounterfactualStep(
                feature=name,
                label=label,
                current=current,
                target=round(needed, 4),
                text=(
                    f"Borrow {amount:,.0f} {case.loan.currency} instead of "
                    f"{case.loan.amount:,.0f}, so the surplus covers the instalment "
                    f"{needed:.1f} times."
                ),
                sufficient=True,
            )
        return None


def _round_down_to_3_figures(amount: Decimal) -> Decimal:
    """A figure an officer would quote, rounded down so the target is still met."""
    digits = len(str(int(amount)))
    quantum = Decimal(10) ** max(digits - 3, 0)
    return (amount / quantum).quantize(Decimal(1), ROUND_DOWN) * quantum


def _logit(probability: float) -> float:
    return math.log(probability / (1 - probability))
