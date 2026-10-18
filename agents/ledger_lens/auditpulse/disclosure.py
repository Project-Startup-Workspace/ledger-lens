"""Key Fact Statement: the loan terms the borrower sees before signing."""

from ledger_lens.shared.loan_math import monthly_instalment
from ledger_lens.shared.schemas import Disclosure, LoanRequest


def key_fact_statement(loan: LoanRequest) -> Disclosure:
    """Disclose APR, instalment, number of instalments and total repayable.

    No fees are modelled yet, so APR equals the nominal annual rate. When fees are
    added they must be folded into the APR, as RBI's directions require.
    """
    instalment = monthly_instalment(loan.amount, loan.annual_rate_pct, loan.tenor_months)
    return Disclosure(
        apr_pct=loan.annual_rate_pct,
        instalment=instalment,
        instalments=loan.tenor_months,
        total_repayable=instalment * loan.tenor_months,
    )
