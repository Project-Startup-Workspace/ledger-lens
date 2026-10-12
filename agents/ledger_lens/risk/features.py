"""Feature definitions: the single list both training and scoring read from."""

from dataclasses import dataclass

from ledger_lens.shared.loan_math import debt_service_coverage, monthly_instalment
from ledger_lens.shared.schemas import CreditFile


@dataclass(frozen=True)
class Feature:
    name: str
    label: str  # plain words for officers and borrowers
    actionable: bool  # whether the applicant can realistically change it before applying


FEATURES: tuple[Feature, ...] = (
    Feature("debt_service_coverage", "Business surplus compared with the instalment", True),
    Feature("sales_volatility", "How much weekly sales swing", False),
    Feature("weeks_of_records", "Weeks of records provided", True),
    Feature("years_in_business", "Years in business", False),
    Feature("wallet_verified", "Notebook checked against a wallet or bank statement", True),
    Feature("mismatch_share", "Share of weeks where notebook and wallet disagree", False),
    Feature("expense_ratio", "Expenses as a share of sales", False),
)
# Coverage beyond 5x tells the model nothing more, and capping keeps the linear fit honest.
# A loss-making business has zero coverage, not negative coverage.
MAX_COVERAGE = 5.0

FEATURE_NAMES = tuple(f.name for f in FEATURES)
BY_NAME = {f.name: f for f in FEATURES}


def extract_features(case: CreditFile) -> dict[str, float]:
    """Build the model input from a case's cash flow, consistency report and loan."""
    if case.cash_flow is None or case.consistency is None:
        raise ValueError("risk needs cash flow and consistency results first")
    flow, check = case.cash_flow, case.consistency
    instalment = monthly_instalment(
        case.loan.amount, case.loan.annual_rate_pct, case.loan.tenor_months
    )
    verified = check.status == "compared"
    return {
        "debt_service_coverage": round(
            min(max(debt_service_coverage(flow.avg_weekly_net, instalment), 0.0), MAX_COVERAGE),
            4,
        ),
        "sales_volatility": round(flow.sales_volatility, 4),
        "weeks_of_records": float(flow.weeks_covered),
        "years_in_business": case.applicant.years_in_business,
        "wallet_verified": 1.0 if verified else 0.0,
        "mismatch_share": check.mismatch_share if verified else 0.0,
        "expense_ratio": round(float(flow.total_expenses / flow.total_sales), 4)
        if flow.total_sales
        else 1.0,
    }
