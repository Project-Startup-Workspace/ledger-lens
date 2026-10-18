"""Week-by-week comparison of notebook sales with wallet or bank inflows.

A shop takes part of its sales by wallet, and that share is fairly stable. A week where
the notebook claims far more (or less) than the usual share is the signature of a page
written after the fact, so it is flagged for the officer to ask about.

Deviation is measured as |log(week share / usual share)|, so inflating the notebook 2x
and the wallet showing 2x more are judged equally.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from ledger_lens.shared.dates import week_start
from ledger_lens.shared.schemas import (
    ConsistencyFlag,
    ConsistencyReport,
    Direction,
    LedgerEntry,
)

Severity = Literal["low", "medium", "high"]

MIN_WEEKS = 3  # fewer comparable weeks than this gives no reliable baseline share
_SEVERITY_WEIGHT = {"low": 0.34, "medium": 0.67, "high": 1.0}


@dataclass
class WeeklySeries:
    """Inflows per ISO week, the days the source covers and weeks it could not read."""

    totals: dict[date, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    first_day: date | None = None
    last_day: date | None = None
    unreadable_weeks: set[date] = field(default_factory=set)

    def covers(self, week: date) -> bool:
        """True when the source spans the whole Monday-to-Sunday week."""
        if self.first_day is None or self.last_day is None:
            return False
        return self.first_day <= week and week + timedelta(days=6) <= self.last_day


def weekly_series(entries: Iterable[LedgerEntry], min_confidence: float) -> WeeklySeries:
    """Sum money in per week; weeks holding an unreadable line are marked, not guessed."""
    series = WeeklySeries()
    for entry in entries:
        day = entry.entry_date
        series.first_day = min(series.first_day or day, day)
        series.last_day = max(series.last_day or day, day)
        if entry.direction is not Direction.IN:
            continue  # only money in is compared; an unread payment changes nothing
        if entry.confidence < min_confidence:
            series.unreadable_weeks.add(week_start(day))
        elif entry.amount > 0:
            series.totals[week_start(day)] += entry.amount
    return series


def compare(
    notebook: WeeklySeries,
    wallet: WeeklySeries,
    tolerance: float,
    currency: str,
    statement_id: str | None = None,
) -> ConsistencyReport:
    """Flag weeks whose wallet share departs from the applicant's own median share."""
    weeks, notes = comparable_weeks(notebook, wallet)
    ratios = {
        w: float(wallet.totals.get(w, Decimal(0)) / notebook.totals[w])
        for w in weeks
        if notebook.totals.get(w)
    }
    baseline = statistics.median(ratios.values()) if len(ratios) >= MIN_WEEKS else 0.0
    if baseline <= 0:
        reason = (
            "Too few comparable weeks to learn the usual wallet share."
            if len(ratios) < MIN_WEEKS
            else "The wallet is rarely used for sales, so it cannot verify the notebook."
        )
        return _insufficient(statement_id, [*notes, reason])

    threshold = math.log1p(tolerance)
    typical_inflow = statistics.median(v for v in wallet.totals.values() if v > 0)
    flags = []
    for week in weeks:
        if week in ratios:
            flag = _share_flag(week, notebook, wallet, ratios[week], baseline, threshold, currency)
        else:
            flag = _blank_week_flag(week, wallet, typical_inflow, baseline, currency)
        if flag:
            flags.append(flag)
    penalty = sum(_SEVERITY_WEIGHT[f.severity] for f in flags) / len(weeks)
    return ConsistencyReport(
        status="compared",
        statement_evidence_id=statement_id,
        weeks_compared=len(weeks),
        baseline_ratio=round(baseline, 4),
        flags=flags,
        mismatch_share=round(len(flags) / len(weeks), 4),
        consistency_score=round(max(0.0, 1 - penalty), 4),
        notes=notes,
    )


def comparable_weeks(notebook: WeeklySeries, wallet: WeeklySeries) -> tuple[list[date], list[str]]:
    """Weeks both sources fully cover, minus weeks where either has an unreadable line.

    An unread line understates that week's total, which would look like a mismatch.
    """
    candidates = sorted(w for w in set(notebook.totals) | set(wallet.totals))
    covered = [w for w in candidates if notebook.covers(w) and wallet.covers(w)]
    unreadable = notebook.unreadable_weeks | wallet.unreadable_weeks
    readable = [w for w in covered if w not in unreadable]
    notes = []
    if skipped := len(covered) - len(readable):
        notes.append(f"{skipped} week(s) skipped because a line there could not be read.")
    return readable, notes


def _severity(deviation: float, threshold: float) -> Severity:
    """Grade relative to the configured tolerance, so tuning it keeps the scale intact."""
    return (
        "high" if deviation > 2 * threshold else "medium" if deviation > 1.5 * threshold else "low"
    )


def _share_flag(
    week: date,
    notebook: WeeklySeries,
    wallet: WeeklySeries,
    ratio: float,
    baseline: float,
    threshold: float,
    currency: str,
) -> ConsistencyFlag | None:
    deviation = abs(math.log(ratio / baseline)) if ratio > 0 else math.inf
    if deviation <= threshold:
        return None
    sales, inflow = notebook.totals[week], wallet.totals.get(week, Decimal(0))
    when = f"the week of {week:%d %b %Y}"
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
        severity=_severity(deviation, threshold),
        explanation=explanation,
        officer_question=question,
    )


def _blank_week_flag(
    week: date, wallet: WeeklySeries, typical: Decimal, baseline: float, currency: str
) -> ConsistencyFlag | None:
    """Wallet money in a week the notebook leaves blank, graded by how much arrived."""
    inflow = wallet.totals.get(week, Decimal(0))
    share = float(inflow / typical) if typical else 0.0
    if share < 0.25:
        return None  # small refunds or test transfers are not worth an officer's question
    when = f"the week of {week:%d %b %Y}"
    return ConsistencyFlag(
        week_start=week,
        notebook_sales=Decimal(0),
        wallet_inflow=inflow,
        ratio=None,
        expected_ratio=round(baseline, 4),
        severity="high" if share >= 1 else "medium" if share >= 0.5 else "low",
        explanation=f"The wallet received {inflow:,.0f} {currency} in {when}, "
        "but the notebook records no sales.",
        officer_question=f"Your wallet received money in {when} but the notebook is "
        "blank. Were you trading that week, and where are those sales written down?",
    )


def _insufficient(statement_id: str | None, notes: list[str]) -> ConsistencyReport:
    return ConsistencyReport(
        status="insufficient_data",
        statement_evidence_id=statement_id,
        weeks_compared=0,
        baseline_ratio=None,
        flags=[],
        mismatch_share=0.0,
        consistency_score=None,
        notes=notes,
    )
