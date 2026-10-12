"""Loan arithmetic shared by the risk model and the disclosure checks."""

from decimal import ROUND_HALF_UP, Decimal

WEEKS_PER_MONTH = Decimal("4.345")  # 52.14 weeks / 12 months
CENT = Decimal("0.01")


def monthly_instalment(principal: Decimal, annual_rate_pct: float, months: int) -> Decimal:
    """Level monthly payment for an amortising loan (zero rate is plain division)."""
    rate = Decimal(str(annual_rate_pct)) / 100 / 12
    if rate == 0:
        return (principal / months).quantize(CENT, ROUND_HALF_UP)
    payment = principal * rate / (1 - (1 + rate) ** -months)
    return payment.quantize(CENT, ROUND_HALF_UP)


def debt_service_coverage(avg_weekly_net: Decimal, instalment: Decimal) -> float:
    """How many times monthly business surplus covers the monthly instalment."""
    if instalment <= 0:
        return 0.0
    return float(avg_weekly_net * WEEKS_PER_MONTH / instalment)
