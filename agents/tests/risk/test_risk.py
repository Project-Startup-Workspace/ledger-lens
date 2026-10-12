"""Risk model mathematics, grading, reasons and the path to approval."""

import math
from decimal import Decimal

import pytest

from ledger_lens.risk.agent import RiskAgent, _round_down_to_3_figures, grade_for
from ledger_lens.risk.features import extract_features
from ledger_lens.risk.model import LogisticModel
from ledger_lens.risk.training import TRUE_EFFECTS, train
from ledger_lens.shared.config import Settings
from ledger_lens.shared.loan_math import debt_service_coverage, monthly_instalment
from ledger_lens.shared.schemas import (
    Applicant,
    CashFlowSummary,
    Consent,
    ConsistencyFlag,
    ConsistencyReport,
    CreditFile,
    LoanRequest,
    RiskGrade,
)


def test_monthly_instalment_matches_amortisation_formula() -> None:
    assert monthly_instalment(Decimal(100_000), 12, 12) == Decimal("8884.88")
    assert monthly_instalment(Decimal(1200), 0, 12) == Decimal("100.00")


def test_debt_service_coverage_uses_weeks_per_month() -> None:
    assert debt_service_coverage(Decimal(1000), Decimal("4345")) == pytest.approx(1.0)
    assert debt_service_coverage(Decimal(1000), Decimal(0)) == 0.0


@pytest.mark.parametrize(
    ("pd", "grade"),
    [
        (0.01, RiskGrade.A),
        (0.05, RiskGrade.B),
        (0.12, RiskGrade.C),
        (0.2, RiskGrade.D),
        (0.5, RiskGrade.E),
    ],
)
def test_grade_bands(pd: float, grade: RiskGrade) -> None:
    assert grade_for(pd) == grade


def test_round_down_to_three_figures() -> None:
    assert _round_down_to_3_figures(Decimal("76980439")) == Decimal(76_900_000)
    assert _round_down_to_3_figures(Decimal("845")) == Decimal(845)


@pytest.fixture(scope="module")
def model() -> LogisticModel:
    return LogisticModel.load(Settings(_env_file=None).risk_model_path)  # type: ignore[call-arg]


def test_shapley_values_sum_to_the_logit_gap(model: LogisticModel) -> None:
    x = dict(zip(model.features, [1.2, 0.5, 10, 2, 0, 0, 0.8], strict=True))
    assert sum(model.attributions(x).values()) == pytest.approx(model.logit(x) - model.intercept)


def test_value_for_logit_inverts_the_model(model: LogisticModel) -> None:
    x = dict(zip(model.features, [1.2, 0.5, 10, 2, 0, 0, 0.8], strict=True))
    weeks = model.value_for_logit(x, "weeks_of_records", -2.5)
    assert model.logit({**x, "weeks_of_records": weeks}) == pytest.approx(-2.5)


def test_training_is_reproducible_and_recovers_effect_directions() -> None:
    a, b = train(n=3000), train(n=3000)
    assert a.coefficients == b.coefficients
    assert a.metrics["holdout_auc"] > 0.7
    for name, coefficient in zip(a.features, a.coefficients, strict=True):
        assert math.copysign(1, coefficient) == math.copysign(1, TRUE_EFFECTS[name])


def make_case(
    weekly_net: int, amount: int, weeks: int = 8, flags: list[ConsistencyFlag] | None = None
) -> CreditFile:
    return CreditFile(
        jurisdiction="lk",
        applicant=Applicant(
            full_name="A",
            date_of_birth="1990-01-01",
            national_id="1",
            phone="1",
            business_name="B",
            business_type="shop",
            years_in_business=3,
        ),
        loan=LoanRequest(
            amount=Decimal(amount), currency="LKR", tenor_months=12, annual_rate_pct=24, purpose="x"
        ),
        consent=Consent(given=True),
        cash_flow=CashFlowSummary(
            currency="LKR",
            weeks=[],
            total_sales=Decimal(weekly_net * 3 * weeks),
            total_expenses=Decimal(weekly_net * 2 * weeks),
            avg_weekly_sales=Decimal(weekly_net * 3),
            avg_weekly_net=Decimal(weekly_net),
            sales_volatility=0.2,
            weeks_covered=weeks,
        ),
        consistency=ConsistencyReport(
            status="compared",
            statement_evidence_id="ev",
            weeks_compared=weeks,
            baseline_ratio=0.4,
            flags=flags or [],
            mismatch_share=len(flags or []) / weeks,
            consistency_score=1.0,
        ),
    )


def test_strong_case_is_approved_with_reasons(model: LogisticModel) -> None:
    result = RiskAgent(model).assess(make_case(weekly_net=20_000, amount=100_000))
    assert result.recommendation == "approve"
    assert result.path_to_approval == []
    assert len(result.reasons) == 4 and all(r.text.endswith("risk.") for r in result.reasons)


def test_high_severity_flag_never_auto_approves(model: LogisticModel) -> None:
    flag = ConsistencyFlag(
        week_start="2026-09-14",
        notebook_sales=Decimal(1),
        wallet_inflow=Decimal(0),
        ratio=0.1,
        expected_ratio=0.4,
        severity="high",
        explanation="x",
        officer_question="y",
    )
    result = RiskAgent(model).assess(make_case(20_000, 100_000, flags=[flag]))
    assert result.recommendation == "refer"


def test_smaller_loan_step_reaches_grade_b_when_applied(model: LogisticModel) -> None:
    case = make_case(weekly_net=4_000, amount=150_000)
    result = RiskAgent(model).assess(case)
    assert result.grade not in {RiskGrade.A, RiskGrade.B}
    [step] = [s for s in result.path_to_approval if s.feature == "debt_service_coverage"]
    assert step.sufficient
    smaller = Decimal(step.text.split()[1].replace(",", ""))
    retry = case.model_copy(update={"loan": case.loan.model_copy(update={"amount": smaller})})
    assert RiskAgent(model).assess(retry).grade in {RiskGrade.A, RiskGrade.B}


def test_features_treat_loss_making_business_as_zero_coverage() -> None:
    case = make_case(weekly_net=-1000, amount=100_000)
    assert extract_features(case)["debt_service_coverage"] == 0.0
