"""Week-by-week comparison of notebook sales with wallet or bank inflows.

A shop takes part of its sales by wallet, and that share is fairly stable. A week where
the notebook claims far more (or less) than the usual share is the signature of a page
written after the fact, so it is flagged for the officer to ask about.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from ledger_lens.evidence.tools import week_start
from ledger_lens.shared.schemas import (
    ConsistencyFlag,
    ConsistencyReport,
    Direction,
    LedgerEntry,
)

MIN_WEEKS = 3  # fewer comparable weeks than this gives no reliable baseline share
_SEVERITY_WEIGHT = {"low": 0.34, "medium": 0.67, "high": 1.0}


def weekly_inflows(entries: Iterable[LedgerEntry], min_confidence: float) -> dict[date, Decimal]:
    """Total money in per ISO week, ignoring lines read with low confidence."""
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for entry in entries:
        if entry.direction is Direction.IN and entry.confidence >= min_confidence:
            totals[week_start(entry.entry_date)] += entry.amount
    return totals


def compare(
    notebook: dict[date, Decimal], wallet: dict[date, Decimal], tolerance: float, currency: str
) -> ConsistencyReport:
    """Flag weeks whose wallet share departs from the applicant's own median share."""
    if not notebook or not wallet:
        return _insufficient(0)
    first, last = max(min(notebook), min(wallet)), min(max(notebook), max(wallet))
    weeks = sorted(w for w in set(notebook) | set(wallet) if first <= w <= last)
    ratios = {w: float(wallet.get(w, 0) / notebook[w]) for w in weeks if notebook.get(w)}
    if len(ratios) < MIN_WEEKS:
        return _insufficient(len(weeks))

    baseline = statistics.median(ratios.values())
    flags = [
        flag
        for week in weeks
        if (flag := _check_week(week, notebook, wallet, ratios, baseline, tolerance, currency))
    ]
    penalty = sum(_SEVERITY_WEIGHT[f.severity] for f in flags) / len(weeks)
    return ConsistencyReport(
        status="compared",
        weeks_compared=len(weeks),
        baseline_ratio=round(baseline, 4),
        flags=flags,
        mismatch_share=round(len(flags) / len(weeks), 4),
        consistency_score=round(max(0.0, 1 - penalty), 4),
    )


def _check_week(
    week: date,
    notebook: dict[date, Decimal],
    wallet: dict[date, Decimal],
    ratios: dict[date, float],
    baseline: float,
    tolerance: float,
    currency: str,
) -> ConsistencyFlag | None:
    sales, inflow = notebook.get(week, Decimal(0)), wallet.get(week, Decimal(0))
    ratio = ratios.get(week)
    when = f"the week of {week:%d %b %Y}"
    if ratio is None:
        return ConsistencyFlag(
            week_start=week,
            notebook_sales=sales,
            wallet_inflow=inflow,
            ratio=None,
            expected_ratio=baseline,
            severity="high",
            explanation=f"The wallet received {inflow:,.0f} {currency} in {when}, "
            "but the notebook records no sales.",
            officer_question=f"Your wallet received money in {when} but the notebook is "
            "blank. Were you trading that week, and where are those sales written down?",
        )
    deviation = abs(ratio - baseline) / baseline if baseline else 0.0
    if deviation <= tolerance:
        return None
    severity = "high" if deviation > 0.5 else "medium" if deviation > 0.42 else "low"
    pct, usual = round(ratio * 100), round(baseline * 100)
    if ratio < baseline:
        explanation = (
            f"In {when} the notebook records {sales:,.0f} {currency} in sales, but only "
            f"{pct}% reached the wallet against a usual {usual}%."
        )
        question = (
            f"Sales in {when} look much higher than the wallet shows. Was there a large "
            "cash sale or an event that week? Can you show receipts or a buyer's name?"
        )
    else:
        explanation = (
            f"In {when} the wallet received {pct}% of recorded sales against a usual "
            f"{usual}%, so the notebook may be missing sales."
        )
        question = (
            f"More money reached your wallet in {when} than the notebook explains. "
            "Did you receive money that was not from sales, such as a loan or a transfer?"
        )
    return ConsistencyFlag(
        week_start=week,
        notebook_sales=sales,
        wallet_inflow=inflow,
        ratio=round(ratio, 4),
        expected_ratio=round(baseline, 4),
        severity=severity,
        explanation=explanation,
        officer_question=question,
    )


def _insufficient(weeks: int) -> ConsistencyReport:
    return ConsistencyReport(
        status="insufficient_data",
        weeks_compared=weeks,
        baseline_ratio=None,
        flags=[],
        mismatch_share=0.0,
        consistency_score=0.0,
    )
